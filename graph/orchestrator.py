"""
Grafo principal del Orquestador de Academia Tesla.
Implementa el patrón Deep Agent + Supervisor usando LangGraph.
"""
from typing import Literal
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from core.estado import AgenteTeslaState
from graph.nodes import node_planificador, node_critico, MAX_ITERACIONES
from agents.sdr_agent import sdr_agent
from agents.admin_agent import admin_agent
from agents.finance_agent import finance_agent
from langchain_core.messages import AIMessage, SystemMessage


def _filter_system_messages(messages: list) -> list:
    """
    Filtra SystemMessages del historial de conversación.
    Cada sub-agente (create_react_agent) ya inyecta su propio system prompt;
    pasar SystemMessages residuales del estado acumulado genera el error
    'Received multiple non-consecutive system messages' de Anthropic.
    """
    return [msg for msg in messages if not isinstance(msg, SystemMessage)]


# ── Envoltorios para sub-grafos ReAct ──────────────────────────────

async def call_sdr(state: AgenteTeslaState):
    """Invoca el sub-agente SDR (ReAct) y retorna su última respuesta."""
    clean_messages = _filter_system_messages(state["messages"])
    response = await sdr_agent.ainvoke({"messages": clean_messages})
    return {
        "messages": response["messages"][-1:],
        "fase": "CAPTACION"
    }


async def call_admin(state: AgenteTeslaState):
    """Invoca el sub-agente Administrativo (ReAct) y retorna su última respuesta."""
    clean_messages = _filter_system_messages(state["messages"])
    
    ciclo_codigo = state.get("ciclo_codigo")
    if ciclo_codigo:
        clean_messages = [
            SystemMessage(content=f"INSTRUCCIÓN CRÍTICA: El código exacto del ciclo seleccionado es '{ciclo_codigo}'. DEBES usar este valor exacto para el parámetro ciclo_codigo en upsert_alumno.")
        ] + clean_messages
        
    response = await admin_agent.ainvoke({"messages": clean_messages})
    return {
        "messages": response["messages"][-1:],
        "fase": "REGISTRO"
    }


async def call_finance(state: AgenteTeslaState):
    """Invoca el sub-agente Financiero (ReAct) y retorna su última respuesta."""
    clean_messages = _filter_system_messages(state["messages"])
    response = await finance_agent.ainvoke({"messages": clean_messages})
    return {
        "messages": response["messages"][-1:],
        "fase": "CIERRE"
    }


def node_escalar(state: AgenteTeslaState):
    """Nodo terminal: escala el caso a atención humana."""
    sid = state.get("session_id", "N/A")
    msg = AIMessage(
        content=(
            "⚠️ **Caso escalado a atención humana**\n\n"
            "Se han detectado múltiples intentos o anomalías en esta sesión. "
            "Un asesor humano revisará su caso a la brevedad.\n\n"
            f"📋 **Session ID:** {sid}\n"
            f"📄 **DNI:** {state.get('dni_alumno', 'N/A')}, "
            f"**Ciclo:** {state.get('ciclo_codigo', 'N/A')}\n\n"
            "Por favor, comuníquese al 📞 (01) 555-0100 o espere a que un asesor lo contacte."
        )
    )
    return {"messages": [msg], "fase": "ESCALAR"}


# ── Enrutamiento condicional ──────────────────────────────────────

def route_plan(state: AgenteTeslaState) -> Literal[
    "agente_sdr", "agente_administrativo", "agente_financiero", "escalar", "__end__"
]:
    """
    Enruta la decisión del planificador al nodo correspondiente.
    Incluye freno de seguridad (add_conditional_edges).
    """
    # Freno de seguridad: límite de iteraciones
    if state.get("iteraciones", 0) >= MAX_ITERACIONES:
        return "escalar"
    
    plan = state.get("plan", "responder_usuario")
    if plan == "agente_sdr":
        return "agente_sdr"
    elif plan == "agente_administrativo":
        return "agente_administrativo"
    elif plan == "agente_financiero":
        return "agente_financiero"
    elif plan == "escalar":
        return "escalar"
    else:
        # "responder_usuario" → el último AIMessage ya es la respuesta
        return "__end__"


def route_critico(state: AgenteTeslaState) -> Literal["planificador", "__end__"]:
    """
    Enruta según el veredicto del crítico.
    APROBADO → terminar (la respuesta es válida).
    RECHAZADO → volver al planificador para corregir.
    """
    if state.get("veredicto") == "APROBADO":
        return "__end__"
    # RECHAZADO: volver al planificador con el feedback
    return "planificador"


# ── Construcción y compilación del grafo ──────────────────────────

def build_graph():
    """Construye el StateGraph del orquestador."""
    builder = StateGraph(AgenteTeslaState)

    # Añadir nodos
    builder.add_node("planificador", node_planificador)
    builder.add_node("agente_sdr", call_sdr)
    builder.add_node("agente_administrativo", call_admin)
    builder.add_node("agente_financiero", call_finance)
    builder.add_node("critico", node_critico)
    builder.add_node("escalar", node_escalar)

    # Flujo: START → planificador → enrutamiento condicional
    builder.add_edge(START, "planificador")
    builder.add_conditional_edges("planificador", route_plan)
    
    # Después de cada agente, evaluación por el crítico
    builder.add_edge("agente_sdr", "critico")
    builder.add_edge("agente_administrativo", "critico")
    builder.add_edge("agente_financiero", "critico")
    
    # Crítico: si aprobado → END, si rechazado → planificador
    builder.add_conditional_edges("critico", route_critico)
    
    # Escalar → END
    builder.add_edge("escalar", END)

    return builder


# ── Compilación del grafo con checkpointer configurable ──────────────
# MemorySaver se usa como fallback local. En startup, main.py recompila
# el grafo con AsyncPostgresSaver cuando DATABASE_URI/DATABASE_URL existe.

def compile_graph(checkpointer=None):
    if checkpointer is None:
        checkpointer = MemorySaver()
    return build_graph().compile(checkpointer=checkpointer)


compiled_graph = compile_graph()
