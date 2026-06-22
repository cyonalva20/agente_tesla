from typing import Literal
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from core.estado import AgenteTeslaState
from graph.nodes import node_planificador, node_critico
from agents.sdr_agent import sdr_agent
from agents.admin_agent import admin_agent
from agents.finance_agent import finance_agent
from langchain_core.messages import AIMessage

# Envoltorios para los sub-grafos para que devuelvan el estado actualizado
async def call_sdr(state: AgenteTeslaState):
    response = await sdr_agent.ainvoke(state)
    return {"messages": response["messages"][-1]}

async def call_admin(state: AgenteTeslaState):
    response = await admin_agent.ainvoke(state)
    return {"messages": response["messages"][-1]}

async def call_finance(state: AgenteTeslaState):
    response = await finance_agent.ainvoke(state)
    return {"messages": response["messages"][-1]}

def node_escalar(state: AgenteTeslaState):
    msg = AIMessage(content="⚠️ Se han detectado múltiples intentos o anomalías. Este caso ha sido escalado a atención humana.")
    return {"messages": [msg], "fase": "ESCALAR"}

def route_plan(state: AgenteTeslaState) -> Literal["agente_sdr", "agente_administrativo", "agente_financiero", "escalar", "__end__"]:
    # Freno de seguridad
    if state.get("iteraciones", 0) >= 3:
        return "escalar"
    
    plan = state.get("plan")
    if plan == "agente_sdr":
        return "agente_sdr"
    elif plan == "agente_administrativo":
        return "agente_administrativo"
    elif plan == "agente_financiero":
        return "agente_financiero"
    elif plan == "escalar":
        return "escalar"
    else:
        return "__end__"

def route_critico(state: AgenteTeslaState) -> Literal["planificador"]:
    # Independientemente del veredicto, el planificador decidirá el siguiente paso
    # Si fue rechazado, el planificador verá la crítica y ordenará corregir.
    # Si fue aprobado, el planificador verá que todo está bien y decidirá "responder_usuario".
    return "planificador"

def build_graph():
    builder = StateGraph(AgenteTeslaState)

    # Añadir nodos
    builder.add_node("planificador", node_planificador)
    builder.add_node("agente_sdr", call_sdr)
    builder.add_node("agente_administrativo", call_admin)
    builder.add_node("agente_financiero", call_finance)
    builder.add_node("critico", node_critico)
    builder.add_node("escalar", node_escalar)

    # Añadir aristas
    builder.add_edge(START, "planificador")
    builder.add_conditional_edges("planificador", route_plan)
    
    # Después de cada agente, se evalúa la respuesta
    builder.add_edge("agente_sdr", "critico")
    builder.add_edge("agente_administrativo", "critico")
    builder.add_edge("agente_financiero", "critico")
    
    # El crítico siempre devuelve el control al planificador
    builder.add_conditional_edges("critico", route_critico)
    
    # Escalar termina la ejecución
    builder.add_edge("escalar", END)

    return builder

# Instancia del grafo (sin compilar aún, se compilará con el checkpointer externamente)
uncompiled_graph = build_graph()
