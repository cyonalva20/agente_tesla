"""
Agente Administrativo de Academia Tesla.
Migrado a LangChain + LangGraph (create_react_agent).
"""
import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from tools.langchain_tools import ADMIN_TOOLS
from tools.logger import get_logger

load_dotenv()

log = get_logger("ADMIN")

SYSTEM_PROMPT = """Eres el Agente Administrativo de Academia Tesla. Tu rol: validar la identidad del alumno y apoderado, y registrar el alumno en la base de datos.

VALIDACIONES OBLIGATORIAS EN ORDEN:
1. Llama a `validar_dni` con el DNI del alumno → verifica que exista en RENIEC
2. Llama a `validar_dni` con el DNI del apoderado → verifica que exista y sea diferente al del alumno
3. Si ambos DNIs son válidos, llama a `upsert_alumno` con todos los datos normalizados
4. Si alguna validación falla, retorna el error específico sin proceder

REGLAS:
- Los nombres deben coincidir (tolerancia de acentos y mayúsculas) con lo que retorna RENIEC
- El teléfono debe tener formato +51XXXXXXXXX
- El estado inicial del alumno siempre es "Registrado"
- Temperatura lógica: respuestas concisas y estructuradas, sin adornos

FORMATO DE RESPUESTA: Siempre retorna un JSON con {"valido": bool, "errores": [], "alumno_id": "uuid_si_guardado"}"""

# LLM para el sub-agente Administrativo
_llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
)

# Agente ReAct precompilado
admin_agent = create_react_agent(
    model=_llm,
    tools=ADMIN_TOOLS,
    prompt=SYSTEM_PROMPT,
)


async def run_admin_agent(
    datos: str,
    historial: list = None,
    session_id: str = None,
) -> str:
    """
    Ejecuta el agente Administrativo con ReAct (LangGraph).
    Recibe los datos del alumno/apoderado y retorna resultado de validación.
    """
    from langchain_core.messages import HumanMessage, AIMessage

    sid = session_id or "-"
    log.info(f"[ADMIN] sid={sid} | START | datos={datos[:120]}")

    messages = []
    if historial:
        for msg in historial:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))

    messages.append(HumanMessage(content=datos))

    try:
        result = await admin_agent.ainvoke({"messages": messages})
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage) and m.content]
        respuesta = ai_messages[-1].content if ai_messages else ""
        log.info(f"[ADMIN] sid={sid} | END | respuesta={respuesta[:200]}")
        return respuesta
    except Exception as e:
        log.error(f"[ADMIN] sid={sid} | EXCEPTION={e}", exc_info=True)
        return f"Error en agente Administrativo: {str(e)}"
