"""
Academia Tesla — Sistema Multiagente CRM
Punto de entrada principal con FastAPI + LangGraph.
"""
import uuid
import json
import asyncio
import os
from typing import Dict, List, Any
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# ── Cargar variables de entorno ANTES de importar LangChain ──
# Esto asegura que LANGSMITH_TRACING y demás estén disponibles.
load_dotenv()

from langchain_core.messages import HumanMessage
from langchain_core.globals import set_debug

# Activar logs detallados para facilitar el debug de los agentes
set_debug(True)

from graph.orchestrator import compiled_graph
from tools.evolution_whatsapp import enviar_mensaje_raw


app = FastAPI(title="Academia Tesla - Sistema Multiagente CRM (LangGraph)")

# Estado en memoria (CRM)
# formato: { phone: { "session_id": str, "agent_enabled": bool, "messages": list, ... } }
sesiones: Dict[str, dict] = {}


# ── Gestor de WebSockets ────────────────────────────────────────

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


# ── Modelos Pydantic ────────────────────────────────────────────

class ToggleRequest(BaseModel):
    enabled: bool

class SendMessageRequest(BaseModel):
    mensaje: str


# ── Rutas base ──────────────────────────────────────────────────

@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep-alive
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ── Gestión de sesiones ─────────────────────────────────────────

def _get_or_create_session(phone: str):
    if phone not in sesiones:
        session_id = str(uuid.uuid4())
        sesiones[phone] = {
            "session_id": session_id,
            "agent_enabled": True,
            "messages": [],
            "last_updated": asyncio.get_event_loop().time(),
            "message_buffer": [],
            "debounce_task": None,
            "telefono": phone
        }
    return sesiones[phone]


# ── Procesamiento con LangGraph ─────────────────────────────────

async def procesar_agente(phone: str, mensaje: str):
    """
    Procesa un mensaje del usuario a través del grafo LangGraph.
    Usa el teléfono como thread_id para persistencia de estado.
    """
    session_info = sesiones.get(phone)
    if not session_info:
        return
    
    try:
        await ws_manager.broadcast({"type": "agent_typing", "phone": phone})
        
        # Invocar el grafo compilado con el estado inicial
        config = {"configurable": {"thread_id": phone}}
        
        result = await compiled_graph.ainvoke(
            {
                "messages": [HumanMessage(content=mensaje)],
                "fase": "CAPTACION",
                "session_id": session_info["session_id"],
                "telefono": phone,
                "iteraciones": 0,
            },
            config=config
        )
        
        # Extraer la última respuesta del asistente
        respuesta = ""
        if result.get("messages"):
            for msg in reversed(result["messages"]):
                if hasattr(msg, "content") and msg.type == "ai":
                    content = msg.content
                    if isinstance(content, str):
                        respuesta = content
                    elif isinstance(content, list):
                        text_blocks = [blk["text"] for blk in content if isinstance(blk, dict) and blk.get("type") == "text"]
                        if text_blocks:
                            respuesta = "\n".join(text_blocks)
                    
                    if respuesta.strip():
                        break
        
        if not respuesta:
            respuesta = "Lo siento, no pude procesar tu solicitud. ¿Podrías reformular tu mensaje?"
        
        # Guardar en CRM
        session_info["messages"].append({"role": "bot", "text": respuesta})
        session_info["last_updated"] = asyncio.get_event_loop().time()
        
        await ws_manager.broadcast({"type": "new_message", "phone": phone})
        
        # Enviar por WhatsApp
        resultado = enviar_mensaje_raw(f"{phone}@s.whatsapp.net", respuesta)
        if not resultado.get("enviado"):
            print(f"[ERROR] Envío WhatsApp falló para {phone}: {resultado.get('error')}")
        
    except Exception as e:
        print(f"Error procesando agente para {phone}: {e}")
        import traceback
        traceback.print_exc()


async def procesar_agente_simulado(phone: str, mensaje: str):
    """Procesamiento simulado (sin envío real por WhatsApp)."""
    session_info = sesiones.get(phone)
    if not session_info:
        return
    
    try:
        await ws_manager.broadcast({"type": "agent_typing", "phone": phone})
        
        config = {"configurable": {"thread_id": f"sim_{phone}"}}
        
        result = await compiled_graph.ainvoke(
            {
                "messages": [HumanMessage(content=mensaje)],
                "fase": "CAPTACION",
                "session_id": session_info["session_id"],
                "telefono": phone,
                "iteraciones": 0,
            },
            config=config
        )
        
        respuesta = ""
        if result.get("messages"):
            for msg in reversed(result["messages"]):
                if hasattr(msg, "content") and msg.type == "ai":
                    respuesta = msg.content
                    break
        
        if not respuesta:
            respuesta = "Lo siento, no pude procesar tu solicitud."
        
        session_info["messages"].append({"role": "bot", "text": respuesta})
        session_info["last_updated"] = asyncio.get_event_loop().time()
        await ws_manager.broadcast({"type": "new_message", "phone": phone})
        
    except Exception as e:
        print(f"Error procesando simulacion para {phone}: {e}")
        import traceback
        traceback.print_exc()


# ── Debounce para mensajes ──────────────────────────────────────

async def debounce_procesar_agente(phone: str, is_simulation: bool = False):
    try:
        await asyncio.sleep(8.0)
    except asyncio.CancelledError:
        return

    try:
        session_info = sesiones.get(phone)
        if not session_info:
            return

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


# ── WEBHOOK EVOLUTION API ───────────────────────────────────────

@app.post("/webhook/evolution")
async def evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    
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
        if "@lid" in remote_jid:
            alt = key.get("senderPn") or key.get("remoteJidAlt")
            if alt and "@lid" not in alt:
                return alt.split("@")[0]
            return ""
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


# ── API CRM ─────────────────────────────────────────────────────

@app.get("/api/conversations")
async def get_conversations():
    convs = []
    for phone, info in sesiones.items():
        last_msg = info["messages"][-1]["text"] if info["messages"] else "Sin mensajes"
        
        # Obtener fase del estado del grafo si existe
        fase = "CAPTACION"
        try:
            snapshot = await compiled_graph.aget_state(
                {"configurable": {"thread_id": phone}}
            )
            if snapshot and snapshot.values:
                fase = snapshot.values.get("fase", "CAPTACION")
        except Exception:
            pass
        
        convs.append({
            "phone": phone,
            "last_message": last_msg,
            "agent_enabled": info["agent_enabled"],
            "fase": fase,
            "last_updated": info["last_updated"]
        })
    convs.sort(key=lambda x: x["last_updated"], reverse=True)
    return convs


@app.get("/api/conversations/{phone}")
async def get_conversation(phone: str):
    if phone not in sesiones:
        raise HTTPException(status_code=404, detail="Not found")
    info = sesiones[phone]
    
    # Obtener estado del grafo
    session_data = {
        "session_id": info["session_id"],
        "fase": "CAPTACION",
        "telefono": phone
    }
    try:
        snapshot = await compiled_graph.aget_state(
            {"configurable": {"thread_id": phone}}
        )
        if snapshot and snapshot.values:
            session_data.update({
                "fase": snapshot.values.get("fase", "CAPTACION"),
                "dni_alumno": snapshot.values.get("dni_alumno"),
                "ciclo_codigo": snapshot.values.get("ciclo_codigo"),
                "alumno_id": snapshot.values.get("alumno_id"),
                "charge_id": snapshot.values.get("charge_id"),
            })
    except Exception:
        pass
    
    return {
        "phone": phone,
        "agent_enabled": info["agent_enabled"],
        "messages": info["messages"],
        "session_data": session_data
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
    resultado = enviar_mensaje_raw(f"{phone}@s.whatsapp.net", req.mensaje)
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


# ── Static files + Entry point ──────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
