"""
Grafo multiagente de Academia Tesla — LangGraph StateGraph.
Reemplaza al orchestrator.py anterior.

Flujo:  router → (sdr | admin | financiero | escalar) → END
"""
import os
import re
import uuid
from dotenv import load_dotenv

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from state import AgentState
from agents.sdr import run_sdr_agent
from agents.administrativo import run_admin_agent
from agents.financiero import run_financiero_agent
from tools.logger import get_logger

load_dotenv()

log = get_logger("GRAPH")

# ── LLM del router (mismo modelo que el orquestador original) ──
_router_llm = ChatAnthropic(
    model="claude-sonnet-4-6",
    max_tokens=512,
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
)

ROUTER_SYSTEM_PROMPT = """Eres el Router del sistema multiagente de Academia Tesla. Tu ÚNICA tarea es analizar el mensaje del usuario y decidir a qué agente delegar.

## DATOS ACUMULADOS DE LA SESIÓN (no los vuelvas a pedir):
- Fase actual: {fase}
- DNI alumno: {dni_alumno}
- Ciclo seleccionado: {ciclo_codigo}
- ID alumno en BD: {alumno_id}
- Charge ID (Stripe): {charge_id}
- Intentos fallidos consecutivos: {intentos_fallidos}

## REGLAS DE ROUTING:
- Si el usuario pregunta sobre ciclos, precios, horarios, o es un usuario nuevo → responde exactamente: FASE:CAPTACION
- Si el usuario proporciona datos para inscripción (DNI, nombres, apoderado) o confirma que quiere registrarse → responde exactamente: FASE:REGISTRO
- Si el usuario dice que ya pagó o proporciona un charge_id/comprobante → responde exactamente: FASE:CIERRE
- Si hay 3+ intentos fallidos o anomalías graves → responde exactamente: FASE:ESCALAR

## INSTRUCCIONES:
Analiza el mensaje y responde SOLAMENTE con una de estas opciones:
FASE:CAPTACION
FASE:REGISTRO
FASE:CIERRE
FASE:ESCALAR

Además, si el mensaje contiene datos relevantes, extráelos en el siguiente formato después de la fase:
DATOS:dni_alumno=XXXXXXXX,ciclo_codigo=XXXX,charge_id=XXXX

Responde SOLO con la fase y opcionalmente los datos. Nada más."""


# ═══════════════════════════════════════════
#  NODOS DEL GRAFO
# ═══════════════════════════════════════════

async def router_node(state: AgentState) -> dict:
    """
    Analiza el último mensaje del usuario y decide la fase/agente.
    """
    sid = state.get("session_id", "-")

    # Si ya estamos en ESCALAR, mantener
    if state.get("fase") == "ESCALAR":
        log.info(f"[GRAPH] sid={sid} | router → ESCALAR (ya escalado)")
        return {"fase": "ESCALAR"}

    # Obtener el último mensaje humano
    last_human = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_human = msg.content
            break

    if not last_human:
        return {"fase": state.get("fase", "CAPTACION")}

    # Construir prompt del router con datos de sesión
    system = ROUTER_SYSTEM_PROMPT.format(
        fase=state.get("fase", "CAPTACION"),
        dni_alumno=state.get("dni_alumno") or "No proporcionado",
        ciclo_codigo=state.get("ciclo_codigo") or "No seleccionado",
        alumno_id=state.get("alumno_id") or "No registrado",
        charge_id=state.get("charge_id") or "No proporcionado",
        intentos_fallidos=state.get("intentos_fallidos", 0),
    )

    try:
        response = await _router_llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=last_human),
        ])

        response_text = response.content.strip().upper()
        log.info(f"[GRAPH] sid={sid} | router raw → {response_text[:100]}")

        # Extraer fase
        updates = {}
        if "FASE:CAPTACION" in response_text:
            updates["fase"] = "CAPTACION"
        elif "FASE:REGISTRO" in response_text:
            updates["fase"] = "REGISTRO"
        elif "FASE:CIERRE" in response_text:
            updates["fase"] = "CIERRE"
        elif "FASE:ESCALAR" in response_text:
            updates["fase"] = "ESCALAR"
        else:
            # Fallback: mantener fase actual
            updates["fase"] = state.get("fase", "CAPTACION")

        # Extraer datos si vienen
        datos_match = re.search(r"DATOS:(.+)", response_text)
        if datos_match:
            datos_str = datos_match.group(1)
            for pair in datos_str.split(","):
                if "=" in pair:
                    key, val = pair.strip().split("=", 1)
                    key = key.strip().lower()
                    val = val.strip()
                    if key in ("dni_alumno", "ciclo_codigo", "charge_id", "alumno_id") and val:
                        updates[key] = val

        log.info(f"[GRAPH] sid={sid} | router → fase={updates.get('fase')} updates={updates}")
        return updates

    except Exception as e:
        log.error(f"[GRAPH] sid={sid} | router EXCEPTION={e}", exc_info=True)
        return {"fase": state.get("fase", "CAPTACION")}


async def sdr_node(state: AgentState) -> dict:
    """Nodo que ejecuta el agente SDR."""
    sid = state.get("session_id", "-")
    telefono = state.get("telefono")

    # Obtener último mensaje del usuario
    last_human = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_human = msg.content
            break

    # Construir historial resumido para el sub-agente
    historial = _build_historial(state, max_msgs=6)

    log.info(f"[GRAPH] sid={sid} | sdr_node | msg={last_human[:120]}")
    respuesta = await run_sdr_agent(
        consulta=last_human,
        historial=historial,
        session_id=sid,
        telefono=telefono,
    )

    # Extraer datos del resultado
    updates = {
        "respuesta_final": respuesta,
        "messages": [AIMessage(content=respuesta)],
    }
    updates.update(_extraer_datos_de_resultado(respuesta))

    return updates


async def admin_node(state: AgentState) -> dict:
    """Nodo que ejecuta el agente Administrativo."""
    sid = state.get("session_id", "-")

    last_human = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_human = msg.content
            break

    historial = _build_historial(state, max_msgs=6)

    log.info(f"[GRAPH] sid={sid} | admin_node | msg={last_human[:120]}")
    respuesta = await run_admin_agent(
        datos=last_human,
        historial=historial,
        session_id=sid,
    )

    updates = {
        "respuesta_final": respuesta,
        "messages": [AIMessage(content=respuesta)],
    }
    updates.update(_extraer_datos_de_resultado(respuesta))

    # Si el registro fue exitoso, avanzar fase
    if '"valido": true' in respuesta.lower() or '"valido":true' in respuesta.lower():
        updates["fase"] = "CIERRE"
        updates["intentos_fallidos"] = 0

    return updates


async def financiero_node(state: AgentState) -> dict:
    """Nodo que ejecuta el agente Financiero."""
    sid = state.get("session_id", "-")

    last_human = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_human = msg.content
            break

    historial = _build_historial(state, max_msgs=6)

    log.info(f"[GRAPH] sid={sid} | financiero_node | msg={last_human[:120]}")
    respuesta = await run_financiero_agent(
        instruccion=last_human,
        historial=historial,
        session_id=sid,
    )

    updates = {
        "respuesta_final": respuesta,
        "messages": [AIMessage(content=respuesta)],
    }
    updates.update(_extraer_datos_de_resultado(respuesta))

    # Si generó constancia, marcar como completado
    if "constancia" in respuesta.lower() and "número" in respuesta.lower():
        updates["fase"] = "COMPLETADO"
        updates["intentos_fallidos"] = 0

    # Detectar escalamiento
    if "[fase:escalar]" in respuesta.lower():
        updates["fase"] = "ESCALAR"

    return updates


async def escalar_node(state: AgentState) -> dict:
    """Nodo de escalamiento a atención humana."""
    sid = state.get("session_id", "-")

    respuesta = (
        "⚠️ **Caso escalado a atención humana**\n\n"
        "Se han detectado múltiples intentos fallidos en esta sesión. "
        "Un asesor humano revisará su caso a la brevedad.\n\n"
        f"📋 **Session ID:** {sid}\n"
        f"📄 **Datos registrados:** DNI: {state.get('dni_alumno', 'N/A')}, "
        f"Ciclo: {state.get('ciclo_codigo', 'N/A')}\n\n"
        "Por favor, comuníquese al 📞 (01) 555-0100 o espere a que un asesor lo contacte."
    )

    log.info(f"[GRAPH] sid={sid} | escalar_node | escalado")

    return {
        "respuesta_final": respuesta,
        "messages": [AIMessage(content=respuesta)],
    }


# ═══════════════════════════════════════════
#  FUNCIONES AUXILIARES
# ═══════════════════════════════════════════

def _build_historial(state: AgentState, max_msgs: int = 6) -> list:
    """Construye un historial resumido como lista de dicts para los sub-agentes."""
    messages = state.get("messages", [])
    recent = messages[-max_msgs:] if len(messages) > max_msgs else messages
    historial = []
    for msg in recent:
        if isinstance(msg, HumanMessage):
            historial.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            historial.append({"role": "assistant", "content": msg.content})
    return historial


def _extraer_datos_de_resultado(resultado: str) -> dict:
    """Extrae datos relevantes del resultado de un sub-agente."""
    updates = {}
    try:
        if '"alumno_id"' in resultado:
            match = re.search(r'"alumno_id"\s*:\s*"([^"]+)"', resultado)
            if match:
                updates["alumno_id"] = match.group(1)

        if '"ciclo_codigo"' in resultado or '"ciclo"' in resultado:
            match = re.search(r'"ciclo_codigo"\s*:\s*"([^"]+)"', resultado)
            if match:
                updates["ciclo_codigo"] = match.group(1)

        if '"dni_alumno"' in resultado or '"dni"' in resultado:
            match = re.search(r'"dni_alumno"\s*:\s*"([^"]+)"', resultado)
            if match:
                updates["dni_alumno"] = match.group(1)

        if '"charge_id"' in resultado:
            match = re.search(r'"charge_id"\s*:\s*"([^"]+)"', resultado)
            if match:
                updates["charge_id"] = match.group(1)

        # Detectar fallos
        if '"error"' in resultado or '"valido": false' in resultado.lower():
            updates["intentos_fallidos"] = updates.get("intentos_fallidos", 0) + 1

    except Exception:
        pass

    return updates


def route_by_fase(state: AgentState) -> str:
    """Función de routing condicional basada en la fase actual."""
    fase = state.get("fase", "CAPTACION")
    if fase == "CAPTACION":
        return "sdr"
    elif fase == "REGISTRO":
        return "admin"
    elif fase == "CIERRE":
        return "financiero"
    elif fase == "ESCALAR":
        return "escalar"
    else:
        # COMPLETADO u otro estado → ir a SDR por defecto
        return "sdr"


# ═══════════════════════════════════════════
#  COMPILAR GRAFO
# ═══════════════════════════════════════════

def _build_graph() -> StateGraph:
    """Construye el StateGraph sin compilar."""
    builder = StateGraph(AgentState)

    # Registrar nodos
    builder.add_node("router", router_node)
    builder.add_node("sdr", sdr_node)
    builder.add_node("admin", admin_node)
    builder.add_node("financiero", financiero_node)
    builder.add_node("escalar", escalar_node)

    # Entry point
    builder.set_entry_point("router")

    # Edges condicionales: router → agente según fase
    builder.add_conditional_edges(
        "router",
        route_by_fase,
        {
            "sdr": "sdr",
            "admin": "admin",
            "financiero": "financiero",
            "escalar": "escalar",
        },
    )

    # Todos los agentes → END
    builder.add_edge("sdr", END)
    builder.add_edge("admin", END)
    builder.add_edge("financiero", END)
    builder.add_edge("escalar", END)

    return builder


async def compilar_grafo(db_path: str = "checkpoints.db"):
    """
    Compila el grafo con persistencia SQLite.
    Retorna (compiled_graph, checkpointer) — el checkpointer se debe cerrar al apagar.
    """
    builder = _build_graph()

    checkpointer_cm = AsyncSqliteSaver.from_conn_string(db_path)
    checkpointer = await checkpointer_cm.__aenter__()

    graph = builder.compile(checkpointer=checkpointer)

    log.info("[GRAPH] Grafo compilado con persistencia SQLite")

    return graph, checkpointer, checkpointer_cm


def compilar_grafo_sin_persistencia():
    """
    Compila el grafo sin persistencia (para pruebas rápidas).
    """
    builder = _build_graph()
    graph = builder.compile()
    log.info("[GRAPH] Grafo compilado sin persistencia (modo test)")
    return graph


def crear_estado_inicial(telefono: str = None) -> dict:
    """Crea un estado inicial para una nueva sesión."""
    return {
        "messages": [],
        "fase": "CAPTACION",
        "dni_alumno": None,
        "ciclo_codigo": None,
        "alumno_id": None,
        "charge_id": None,
        "intentos_fallidos": 0,
        "session_id": str(uuid.uuid4()),
        "telefono": telefono,
        "respuesta_final": None,
    }
