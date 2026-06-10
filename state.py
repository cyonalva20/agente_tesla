"""
Estado compartido del sistema multiagente de Academia Tesla.
Define el TypedDict que viaja por todos los nodos del grafo LangGraph.
"""
from typing import Optional, Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Estado global del grafo multiagente."""

    # ── Historial de mensajes (acumulativo vía add_messages) ──
    messages: Annotated[list, add_messages]

    # ── FSM del embudo ──
    fase: str  # CAPTACION | REGISTRO | CIERRE | ESCALAR | COMPLETADO

    # ── Datos acumulados de la sesión ──
    dni_alumno: Optional[str]
    ciclo_codigo: Optional[str]
    alumno_id: Optional[str]
    charge_id: Optional[str]
    intentos_fallidos: int
    session_id: str
    telefono: Optional[str]

    # ── Respuesta final para el usuario ──
    respuesta_final: Optional[str]
