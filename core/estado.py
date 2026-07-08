from typing import Annotated, TypedDict, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class AgenteTeslaState(TypedDict):
    """
    Estado global del Grafo principal del Orquestador de Academia Tesla.
    """
    # Historial conversacional gestionado por LangGraph
    messages: Annotated[list[BaseMessage], add_messages]
    
    # Datos de negocio extraídos durante la sesión
    fase: str
    dni_alumno: Optional[str]
    ciclo_codigo: Optional[str]
    alumno_id: Optional[str]
    charge_id: Optional[str]
    email_pago: Optional[str]
    session_id: str
    telefono: Optional[str]
    
    # Variables de control para el patrón Supervisor (Deep Agent)
    plan: Optional[str]
    iteraciones: int
    veredicto: Optional[str]
