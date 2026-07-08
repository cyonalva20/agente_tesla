"""
Academia Tesla — Sistema Multiagente CRM
Punto de entrada principal con FastAPI + LangGraph.
"""
import asyncio
import os
from typing import Dict, List
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# ── Cargar variables de entorno ANTES de importar LangChain ──
# Esto asegura que LANGSMITH_TRACING y demás estén disponibles.
load_dotenv()


def configure_langsmith() -> None:
    """Enable LangSmith tracing when credentials are available."""
    if os.getenv("LANGSMITH_API_KEY"):
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGCHAIN_TRACING_V2", os.environ["LANGSMITH_TRACING"])
        os.environ.setdefault("LANGSMITH_PROJECT", "agente-tesla")
    else:
        os.environ.setdefault("LANGSMITH_TRACING", "false")


configure_langsmith()

from langchain_core.messages import HumanMessage
from langchain_core.messages import AIMessage
from langchain_core.globals import set_debug

# Activar logs detallados para facilitar el debug de los agentes
set_debug(True)

from graph.orchestrator import compile_graph
from core.session_store import InMemorySessionStore, create_session_store, normalize_database_uri
from tools.evolution_whatsapp import enviar_mensaje_raw


app = FastAPI(title="Academia Tesla - Sistema Multiagente CRM (LangGraph)")

session_store = create_session_store()
runtime_sessions: Dict[str, dict] = {}
compiled_graph = compile_graph()
_checkpointer_cm = None


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


@app.on_event("startup")
async def startup_event():
    global compiled_graph, _checkpointer_cm, session_store
    try:
        session_store.setup()
    except Exception as exc:
        print(
            "[WARN] Persistent session store unavailable; "
            f"falling back to in-memory sessions: {exc}"
        )
        session_store = InMemorySessionStore()
        session_store.setup()
        return

    database_uri = os.getenv("DATABASE_URI") or os.getenv("DATABASE_URL")
    if database_uri:
        os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        try:
            _checkpointer_cm = AsyncPostgresSaver.from_conn_string(
                normalize_database_uri(database_uri)
            )
            checkpointer = await _checkpointer_cm.__aenter__()
            await checkpointer.setup()
            compiled_graph = compile_graph(checkpointer=checkpointer)
        except Exception as exc:
            print(
                "[WARN] LangGraph Postgres checkpointer unavailable; "
                f"using in-memory checkpointer: {exc}"
            )
            if _checkpointer_cm is not None:
                await _checkpointer_cm.__aexit__(None, None, None)
                _checkpointer_cm = None
            compiled_graph = compile_graph()


@app.on_event("shutdown")
async def shutdown_event():
    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)


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
    session_info = session_store.get_or_create_session(phone)
    if phone not in runtime_sessions:
        runtime_sessions[phone] = {
            "message_buffer": [],
            "debounce_task": None,
        }
    return session_info


def _get_runtime_session(phone: str):
    _get_or_create_session(phone)
    return runtime_sessions[phone]


def _messages_for_graph(messages: list[dict]):
    graph_messages = []
    for msg in messages:
        role = msg.get("role")
        text = msg.get("text", "")
        if role == "user":
            graph_messages.append(HumanMessage(content=text))
        elif role in {"bot", "human"}:
            graph_messages.append(AIMessage(content=text))
    return graph_messages


async def _has_graph_checkpoint(thread_id: str) -> bool:
    try:
        snapshot = await compiled_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        return bool(snapshot and snapshot.values and snapshot.values.get("messages"))
    except Exception:
        return False


# ── Procesamiento con LangGraph ─────────────────────────────────

async def procesar_agente(phone: str, mensaje: str):
    """
    Procesa un mensaje del usuario a través del grafo LangGraph.
    Usa el teléfono como thread_id para persistencia de estado.
    """
    session_info = session_store.get_session(phone)
    if not session_info:
        return
    
    try:
        await ws_manager.broadcast({"type": "agent_typing", "phone": phone})
        
        # Invocar el grafo compilado con el estado inicial
        config = {"configurable": {"thread_id": phone}}
        
        input_messages = [HumanMessage(content=mensaje)]
        if not await _has_graph_checkpoint(phone):
            input_messages = _messages_for_graph(session_store.get_messages(phone))

        result = await compiled_graph.ainvoke(
            {
                "messages": input_messages,
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
        session_store.append_message(phone, "bot", respuesta)
        
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
    session_info = session_store.get_session(phone)
    if not session_info:
        return
    
    try:
        await ws_manager.broadcast({"type": "agent_typing", "phone": phone})
        
        config = {"configurable": {"thread_id": f"sim_{phone}"}}
        
        thread_id = f"sim_{phone}"
        input_messages = [HumanMessage(content=mensaje)]
        if not await _has_graph_checkpoint(thread_id):
            input_messages = _messages_for_graph(session_store.get_messages(phone))

        result = await compiled_graph.ainvoke(
            {
                "messages": input_messages,
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
        
        session_store.append_message(phone, "bot", respuesta)
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
        if not session_store.get_session(phone):
            return

        runtime_info = runtime_sessions.get(phone, {})
        buffer = runtime_info.get("message_buffer", [])
        if not buffer:
            return
        
        mensaje_unido = " ".join(buffer)
        runtime_info["message_buffer"] = []
        runtime_info["debounce_task"] = None

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
    runtime_info = _get_runtime_session(phone)
    
    if from_me:
        pass
    else:
        # Mensaje de usuario
        msg_obj = {"role": "user", "text": text}
        session_store.append_message(phone, "user", msg_obj["text"])
        runtime_info["message_buffer"].append(text)
        await ws_manager.broadcast({"type": "new_message", "phone": phone})

        # Procesar con Agente si esta activo
        if session_info["agent_enabled"]:
            if runtime_info.get("debounce_task"):
                runtime_info["debounce_task"].cancel()
            runtime_info["debounce_task"] = asyncio.create_task(
                debounce_procesar_agente(phone)
            )
        
    return {"status": "ok"}


# ── API CRM ─────────────────────────────────────────────────────

@app.get("/api/conversations")
async def get_conversations():
    convs = []
    for info in session_store.list_conversations():
        phone = info["phone"]
        
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
            "last_message": info["last_message"],
            "agent_enabled": info["agent_enabled"],
            "fase": fase,
            "last_updated": info["last_updated"]
        })
    return convs


@app.get("/api/conversations/{phone}")
async def get_conversation(phone: str):
    info = session_store.get_session(phone)
    if not info:
        raise HTTPException(status_code=404, detail="Not found")
    
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
        "messages": session_store.get_messages(phone),
        "session_data": session_data
    }


@app.post("/api/conversations/{phone}/toggle")
async def toggle_agent(phone: str, req: ToggleRequest):
    session_store.set_agent_enabled(phone, req.enabled)
    await ws_manager.broadcast({"type": "agent_toggled", "phone": phone, "enabled": req.enabled})
    return {"status": "ok", "enabled": req.enabled}


@app.post("/api/conversations/{phone}/send")
async def manual_send(phone: str, req: SendMessageRequest):
    _get_or_create_session(phone)
    session_store.append_message(phone, "human", req.mensaje)
    
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
    runtime_info = _get_runtime_session(phone)
    session_store.append_message(phone, "user", req.mensaje)
    runtime_info["message_buffer"].append(req.mensaje)
    
    await ws_manager.broadcast({"type": "new_message", "phone": phone})
    
    if session_info["agent_enabled"]:
        if runtime_info.get("debounce_task"):
            runtime_info["debounce_task"].cancel()
        runtime_info["debounce_task"] = asyncio.create_task(
            debounce_procesar_agente(phone, is_simulation=True)
        )
        
    return {"status": "ok"}


# ── Static files + Entry point ──────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
