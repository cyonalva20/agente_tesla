import uuid
import json
import asyncio
from typing import Dict, List, Any
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os

from langchain_core.messages import HumanMessage
from graph import compilar_grafo, crear_estado_inicial
from tools.evolution_whatsapp import enviar_mensaje

app = FastAPI(title="Academia Tesla - Sistema Multiagente CRM (LangGraph)")

# ── Grafo global y checkpointer ──
_graph = None
_checkpointer = None
_checkpointer_cm = None

# Estado en memoria (CRM)
# formato: { phone: { "session_id": str, "agent_enabled": bool, "messages": list, "last_updated": float } }
sesiones: Dict[str, dict] = {}

# Gestor de WebSockets para notificar al frontend
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

ws_manager = ConnectionManager()

class ToggleRequest(BaseModel):
    enabled: bool

class SendMessageRequest(BaseModel):
    mensaje: str


@app.on_event("startup")
async def startup():
    """Compila el grafo con persistencia SQLite al iniciar."""
    global _graph, _checkpointer, _checkpointer_cm
    _graph, _checkpointer, _checkpointer_cm = await compilar_grafo("checkpoints.db")


@app.on_event("shutdown")
async def shutdown():
    """Cierra el checkpointer al apagar."""
    global _checkpointer_cm
    if _checkpointer_cm:
        await _checkpointer_cm.__aexit__(None, None, None)


@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() # keep-alive
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

def _get_or_create_session(phone: str):
    if phone not in sesiones:
        estado_inicial = crear_estado_inicial(telefono=phone)
        sesiones[phone] = {
            "session_id": estado_inicial["session_id"],
            "agent_enabled": True,
            "messages": [],
            "last_updated": asyncio.get_event_loop().time(),
            "message_buffer": [],
            "debounce_task": None,
            "fase": "CAPTACION",
        }
    return sesiones[phone]

# --- WEBHOOK EVOLUTION API ---
@app.post("/webhook/evolution")
async def evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    
    # Dependiendo de la version, la estructura varia. Asumimos estructura standard:
    event = data.get("event", "")
    if event != "messages.upsert":
        return {"status": "ignored"}
        
    msg_data = data.get("data", {})
    key = msg_data.get("key", {})
    from_me = key.get("fromMe", False)
    remote_jid = key.get("remoteJid", "")
    
    # Ignorar mensajes de grupos o estados
    if not remote_jid or "@g.us" in remote_jid or "status" in remote_jid:
        return {"status": "ignored"}

    def _resolver_numero(key: dict, remote_jid: str) -> str:
        # Si es LID, el número real está en senderPn (o remoteJidAlt en otras versiones)
        if "@lid" in remote_jid:
            alt = key.get("senderPn") or key.get("remoteJidAlt")
            if alt and "@lid" not in alt:
                return alt.split("@")[0]
            return ""  # no hay número válido, no intentamos responder
            
        return remote_jid.split("@")[0]
        
    phone = _resolver_numero(key, remote_jid)
    if not phone:
        print(f"[WARN] No se pudo resolver número real para {remote_jid}")
        return {"status": "no_phone"}
    
    # Extraer texto del mensaje
    message_content = msg_data.get("message", {})
    
    def _extract_text(msg_content: dict) -> str:
        if not isinstance(msg_content, dict): return ""
        if "conversation" in msg_content:
            return msg_content["conversation"]
        if "extendedTextMessage" in msg_content:
            return msg_content["extendedTextMessage"].get("text", "")
        if "ephemeralMessage" in msg_content:
            return _extract_text(msg_content["ephemeralMessage"].get("message", {}))
        if "viewOnceMessage" in msg_content:
            return _extract_text(msg_content["viewOnceMessage"].get("message", {}))
        if "viewOnceMessageV2" in msg_content:
            return _extract_text(msg_content["viewOnceMessageV2"].get("message", {}))
        return ""

    text = _extract_text(message_content)
        
    if not text:
        print(f"[WARN] Webhook ignorado (sin texto). message_keys: {list(message_content.keys())}")
        return {"status": "no_text"}

    session_info = _get_or_create_session(phone)
    session_info["last_updated"] = asyncio.get_event_loop().time()
    
    # Si el mensaje fue enviado por el bot/humano (from_me), no lo duplicamos
    if from_me:
        pass
    else:
        # Mensaje de usuario
        msg_obj = {"role": "user", "text": text}
        session_info["messages"].append(msg_obj)
        session_info["message_buffer"].append(text)
        await ws_manager.broadcast({"type": "new_message", "phone": phone})

        # Procesar con Agente si esta activo
        if session_info["agent_enabled"]:
            if session_info.get("debounce_task"):
                session_info["debounce_task"].cancel()
            session_info["debounce_task"] = asyncio.create_task(
                debounce_procesar_agente(phone)
            )
        
    return {"status": "ok"}

async def debounce_procesar_agente(phone: str, is_simulation: bool = False):
    try:
        await asyncio.sleep(8.0)
    except asyncio.CancelledError:
        return

    try:
        session_info = sesiones.get(phone)
        if not session_info: return

        buffer = session_info.get("message_buffer", [])
        if not buffer:
            return
        
        mensaje_unido = " ".join(buffer)
        session_info["message_buffer"] = []
        session_info["debounce_task"] = None

        if is_simulation:
            await procesar_agente_simulado(phone, mensaje_unido)
        else:
            await procesar_agente(phone, mensaje_unido)
    except Exception as e:
        print(f"[ERROR] En debounce_procesar_agente para {phone}: {e}")

async def procesar_agente(phone: str, mensaje: str):
    """Procesa un mensaje del usuario a través del grafo LangGraph."""
    session_info = sesiones.get(phone)
    if not session_info: return
    
    try:
        await ws_manager.broadcast({"type": "agent_typing", "phone": phone})
        
        respuesta = await _invocar_grafo(phone, mensaje, session_info)
        
        # Guardar en CRM primero para que se vea rápido
        session_info["messages"].append({"role": "bot", "text": respuesta})
        session_info["last_updated"] = asyncio.get_event_loop().time()
        
        await ws_manager.broadcast({"type": "new_message", "phone": phone})
        
        # Enviar por whatsapp
        resultado = enviar_mensaje(f"{phone}@s.whatsapp.net", respuesta)
        if not resultado.get("enviado"):
            print(f"[ERROR] Envío WhatsApp falló para {phone}: {resultado.get('error')}")
        
    except Exception as e:
        print(f"Error procesando agente para {phone}: {e}")


async def _invocar_grafo(phone: str, mensaje: str, session_info: dict) -> str:
    """
    Invoca el grafo LangGraph con persistencia.
    Usa el session_id como thread_id para el checkpointer.
    """
    global _graph
    
    sid = session_info["session_id"]
    
    # Configuración del thread para persistencia
    config = {"configurable": {"thread_id": sid}}
    
    # Invocar el grafo con el nuevo mensaje
    input_state = {
        "messages": [HumanMessage(content=mensaje)],
        "telefono": phone,
        "session_id": sid,
    }
    
    result = await _graph.ainvoke(input_state, config=config)
    
    # Actualizar la fase en la sesión CRM
    session_info["fase"] = result.get("fase", session_info.get("fase", "CAPTACION"))
    
    # Extraer respuesta final
    respuesta = result.get("respuesta_final", "")
    if not respuesta:
        # Fallback: obtener el último AIMessage
        from langchain_core.messages import AIMessage
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                respuesta = msg.content
                break
    
    return respuesta or "Lo siento, hubo un error procesando tu mensaje. Por favor intenta de nuevo."


# --- API CRM ---
@app.get("/api/conversations")
async def get_conversations():
    convs = []
    for phone, info in sesiones.items():
        last_msg = info["messages"][-1]["text"] if info["messages"] else "Sin mensajes"
        convs.append({
            "phone": phone,
            "last_message": last_msg,
            "agent_enabled": info["agent_enabled"],
            "fase": info.get("fase", "CAPTACION"),
            "last_updated": info["last_updated"]
        })
    convs.sort(key=lambda x: x["last_updated"], reverse=True)
    return convs

@app.get("/api/conversations/{phone}")
async def get_conversation(phone: str):
    if phone not in sesiones:
        raise HTTPException(status_code=404, detail="Not found")
    info = sesiones[phone]
    return {
        "phone": phone,
        "agent_enabled": info["agent_enabled"],
        "messages": info["messages"],
        "session_data": {
            "session_id": info["session_id"],
            "fase": info.get("fase", "CAPTACION"),
        }
    }

@app.post("/api/conversations/{phone}/toggle")
async def toggle_agent(phone: str, req: ToggleRequest):
    if phone not in sesiones:
        _get_or_create_session(phone)
    sesiones[phone]["agent_enabled"] = req.enabled
    await ws_manager.broadcast({"type": "agent_toggled", "phone": phone, "enabled": req.enabled})
    return {"status": "ok", "enabled": req.enabled}

@app.post("/api/conversations/{phone}/send")
async def manual_send(phone: str, req: SendMessageRequest):
    if phone not in sesiones:
        _get_or_create_session(phone)
    
    info = sesiones[phone]
    info["messages"].append({"role": "human", "text": req.mensaje})
    info["last_updated"] = asyncio.get_event_loop().time()
    
    await ws_manager.broadcast({"type": "new_message", "phone": phone})
    
    # Enviar por whatsapp
    resultado = enviar_mensaje(f"{phone}@s.whatsapp.net", req.mensaje)
    if not resultado.get("enviado"):
        print(f"[ERROR] Envío manual fallido para {phone}: {resultado.get('error')}")
        
    return {"status": "ok"}

# Endpoint para simulacion local (sin whatsapp real)
@app.post("/api/conversations/{phone}/simulate_user")
async def simulate_user(phone: str, req: SendMessageRequest, background_tasks: BackgroundTasks):
    session_info = _get_or_create_session(phone)
    session_info["last_updated"] = asyncio.get_event_loop().time()
    session_info["messages"].append({"role": "user", "text": req.mensaje})
    session_info["message_buffer"].append(req.mensaje)
    
    await ws_manager.broadcast({"type": "new_message", "phone": phone})
    
    if session_info["agent_enabled"]:
        if session_info.get("debounce_task"):
            session_info["debounce_task"].cancel()
        session_info["debounce_task"] = asyncio.create_task(
            debounce_procesar_agente(phone, is_simulation=True)
        )
        
    return {"status": "ok"}

async def procesar_agente_simulado(phone: str, mensaje: str):
    """Procesa un mensaje simulado a través del grafo LangGraph (sin enviar WhatsApp)."""
    session_info = sesiones.get(phone)
    if not session_info: return
    
    try:
        await ws_manager.broadcast({"type": "agent_typing", "phone": phone})
        
        respuesta = await _invocar_grafo(phone, mensaje, session_info)
        
        session_info["messages"].append({"role": "bot", "text": respuesta})
        session_info["last_updated"] = asyncio.get_event_loop().time()
        await ws_manager.broadcast({"type": "new_message", "phone": phone})
    except Exception as e:
        print(f"Error procesando simulacion para {phone}: {e}")

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
