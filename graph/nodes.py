from core.estado import AgenteTeslaState
from core.llm import llm_haiku, llm
from core.prompts import planner_prompt
from langchain_core.messages import SystemMessage, HumanMessage
import json

def node_planificador(state: AgenteTeslaState):
    """
    Nodo Supervisor que decide el siguiente paso a ejecutar.
    """
    messages = state["messages"]
    fase = state.get("fase", "CAPTACION")
    
    # Prompting al LLM rápido para decidir qué agente ejecutar
    prompt_value = planner_prompt.invoke({
        "messages": messages,
        "fase": fase,
        "dni_alumno": state.get("dni_alumno", "Aún no proporcionado"),
        "ciclo_codigo": state.get("ciclo_codigo", "Aún no seleccionado"),
        "alumno_id": state.get("alumno_id", "No registrado aún"),
        "charge_id": state.get("charge_id", "No proporcionado"),
        "intentos_fallidos": state.get("intentos_fallidos", 0)
    })
    
    # Le pedimos que estructure su decisión como JSON
    structured_llm = llm_haiku.with_structured_output(
        schema={
            "name": "Plan",
            "description": "Planifica el siguiente paso en la conversación",
            "parameters": {
                "type": "object",
                "properties": {
                    "siguiente_agente": {
                        "type": "string",
                        "enum": ["agente_sdr", "agente_administrativo", "agente_financiero", "responder_usuario", "escalar"],
                        "description": "El próximo agente o acción a tomar."
                    },
                    "razonamiento": {"type": "string"}
                },
                "required": ["siguiente_agente", "razonamiento"]
            }
        }
    )
    
    plan_output = structured_llm.invoke(prompt_value)
    
    return {
        "plan": plan_output.get("siguiente_agente", "responder_usuario"),
        "iteraciones": state.get("iteraciones", 0) + 1
    }

def node_critico(state: AgenteTeslaState):
    """
    Nodo que evalúa si la respuesta generada es apropiada y cumple las reglas.
    """
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""
    
    eval_prompt = f"""
    Evalúa la siguiente respuesta generada por uno de los agentes de Academia Tesla:
    "{last_message}"
    
    Reglas:
    1. Si la respuesta pide datos que ya se tienen en la sesión, el veredicto es 'RECHAZADO'.
    2. Si la respuesta inventa precios o ciclos que no vienen de Supabase, es 'RECHAZADO'.
    3. Si la respuesta es grosera, 'RECHAZADO'.
    4. En cualquier otro caso razonable, 'APROBADO'.
    
    Responde en formato JSON estructurado.
    """
    
    structured_llm = llm_haiku.with_structured_output(
        schema={
            "name": "Critica",
            "description": "Veredicto sobre la calidad de la respuesta",
            "parameters": {
                "type": "object",
                "properties": {
                    "veredicto": {
                        "type": "string",
                        "enum": ["APROBADO", "RECHAZADO"],
                        "description": "Veredicto final."
                    },
                    "feedback": {"type": "string"}
                },
                "required": ["veredicto", "feedback"]
            }
        }
    )
    
    eval_output = structured_llm.invoke([HumanMessage(content=eval_prompt)])
    
    # Si fue rechazado, agregamos el feedback como mensaje para que el sistema se corrija
    if eval_output.get("veredicto") == "RECHAZADO":
        return {
            "veredicto": "RECHAZADO",
            "messages": [SystemMessage(content=f"Crítica interna: {eval_output.get('feedback')}. Por favor, corrige tu respuesta.")]
        }
    else:
        return {
            "veredicto": "APROBADO"
        }
