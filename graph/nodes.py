from core.estado import AgenteTeslaState
from core.llm import llm_haiku, llm
from core.prompts import planner_prompt
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
import json


MAX_ITERACIONES = 6  # Freno de seguridad para el patrón Deep Agent


def node_planificador(state: AgenteTeslaState):
    """
    Nodo Supervisor que decide el siguiente paso a ejecutar.
    Usa structured output para obtener una decisión clara.
    """
    messages = state["messages"]
    fase = state.get("fase", "CAPTACION")
    iteraciones = state.get("iteraciones", 0)
    
    # Filtrar SystemMessages del historial para evitar el error
    # "Received multiple non-consecutive system messages" de Anthropic.
    # El planner_prompt ya inyecta su propio SystemMessage al inicio;
    # cualquier SystemMessage residual (p.ej. del crítico) en el historial
    # genera mensajes de sistema no consecutivos que Anthropic rechaza.
    filtered_messages = [
        msg for msg in messages
        if not isinstance(msg, SystemMessage)
    ]
    
    # Prompting al LLM rápido para decidir qué agente ejecutar
    prompt_value = planner_prompt.invoke({
        "messages": filtered_messages,
        "fase": fase,
        "dni_alumno": state.get("dni_alumno", "Aún no proporcionado"),
        "ciclo_codigo": state.get("ciclo_codigo", "Aún no seleccionado"),
        "alumno_id": state.get("alumno_id", "No registrado aún"),
        "charge_id": state.get("charge_id", "No proporcionado"),
        "email_pago": state.get("email_pago", "No proporcionado"),
        "intentos_fallidos": iteraciones
    })
    
    # Structured output para decisión del planificador
    structured_llm = llm_haiku.with_structured_output(
        schema={
            "name": "Plan",
            "description": "Planifica el siguiente paso en la conversación",
            "parameters": {
                "type": "object",
                "properties": {
                    "siguiente_agente": {
                        "type": "string",
                        "enum": [
                            "agente_sdr",
                            "agente_administrativo",
                            "agente_financiero",
                            "responder_usuario",
                            "escalar"
                        ],
                        "description": "El próximo agente o acción a tomar."
                    },
                    "razonamiento": {
                        "type": "string",
                        "description": "Razón breve de la decisión."
                    }
                },
                "required": ["siguiente_agente", "razonamiento"]
            }
        }
    )
    
    plan_output = structured_llm.invoke(prompt_value)
    
    return {
        "plan": plan_output.get("siguiente_agente", "responder_usuario"),
        "iteraciones": iteraciones + 1
    }


def node_critico(state: AgenteTeslaState):
    """
    Nodo que evalúa si la respuesta generada es apropiada y cumple las reglas.
    Sub-agente "Crítico" del patrón Deep Agent.
    """
    messages = state["messages"]
    last_message = messages[-1].content if messages else ""
    fase = state.get("fase", "CAPTACION")
    
    eval_prompt = f"""Evalúa la siguiente respuesta generada por un agente de Academia Tesla:
    
Fase actual: {fase}
DNI alumno: {state.get('dni_alumno', 'N/A')}
Ciclo: {state.get('ciclo_codigo', 'N/A')}

Respuesta a evaluar:
\"{last_message}\"

Reglas:
1. Es NORMAL y ESPERADO que el agente pida el nombre del apoderado, el DNI o el teléfono si el usuario aún no los ha dado explícitamente. No asumas que ya los tiene.
2. ASUME que los precios, horarios y códigos de ciclos mostrados por el agente SON CORRECTOS y han sido extraídos de la base de datos mediante herramientas. NO lo rechaces por "inventar precios" a menos que sea algo ilógico o absurdo.
3. Si la respuesta es grosera o inapropiada → RECHAZADO
4. En cualquier otro caso razonable (como pedir datos para continuar el proceso, dar opciones de ciclos, o confirmar una validación) → APROBADO

Responde en formato JSON estructurado."""
    
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
                    "feedback": {
                        "type": "string",
                        "description": "Retroalimentación breve."
                    }
                },
                "required": ["veredicto", "feedback"]
            }
        }
    )
    
    eval_output = structured_llm.invoke([HumanMessage(content=eval_prompt)])
    
    # Si fue rechazado, agregamos feedback como HumanMessage (no SystemMessage)
    # para evitar "multiple non-consecutive system messages" de Anthropic.
    if eval_output.get("veredicto") == "RECHAZADO":
        return {
            "veredicto": "RECHAZADO",
            "messages": [HumanMessage(
                content=f"[FEEDBACK INTERNO DEL CRÍTICO]: {eval_output.get('feedback')}. "
                        f"Por favor, corrige tu respuesta."
            )]
        }
    else:
        return {
            "veredicto": "APROBADO"
        }
