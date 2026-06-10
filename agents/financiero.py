"""
Agente Financiero de Academia Tesla.
Migrado a LangChain + LangGraph (create_react_agent).
"""
import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from tools.langchain_tools import FINANCIERO_TOOLS
from tools.logger import get_logger

load_dotenv()

log = get_logger("FIN")

SYSTEM_PROMPT = """Eres el Agente Financiero de Academia Tesla. Tu rol: verificar pagos y emitir constancias de matrícula oficiales.

REGLA DE ORO — ABSOLUTA E INNEGOCIABLE:
NUNCA generes una constancia de matrícula si el estado del pago no es exactamente "paid".
Si el pago falla, informa el error y sugiere intentar nuevamente o escalar a atención humana.

PROCESO:
1. Llama a `verificar_pago` con el charge_id proporcionado
2. Si status == "paid":
   a. Llama a `generar_constancia` con alumno_id y ciclo_codigo
   b. Llama a `actualizar_estado` con nuevo_estado="Matriculado" y los datos de la constancia
   c. Llama a `enviar_whatsapp` para notificar al apoderado con el PDF
   d. Retorna confirmación con número de constancia
3. Si status != "paid": retorna el error sin ejecutar ningún paso más

ESCALAMIENTO: Si el pago falla 3 veces, indica explícitamente [FASE:ESCALAR] en tu respuesta."""

# LLM para el sub-agente Financiero
_llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
)

# Agente ReAct precompilado
financiero_agent = create_react_agent(
    model=_llm,
    tools=FINANCIERO_TOOLS,
    prompt=SYSTEM_PROMPT,
)


async def run_financiero_agent(
    instruccion: str,
    historial: list = None,
    session_id: str = None,
) -> str:
    """
    Ejecuta el agente Financiero con ReAct (LangGraph).
    Recibe datos de pago y retorna confirmación o error.
    """
    from langchain_core.messages import HumanMessage, AIMessage

    sid = session_id or "-"
    log.info(f"[FIN] sid={sid} | START | input={instruccion[:120]}")

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

    messages.append(HumanMessage(content=instruccion))

    try:
        result = await financiero_agent.ainvoke({"messages": messages})
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage) and m.content]
        respuesta = ai_messages[-1].content if ai_messages else ""
        log.info(f"[FIN] sid={sid} | END | respuesta={respuesta[:200]}")
        return respuesta
    except Exception as e:
        log.error(f"[FIN] sid={sid} | EXCEPTION={e}", exc_info=True)
        return f"Error en agente Financiero: {str(e)}"