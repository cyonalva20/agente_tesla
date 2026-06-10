"""
Agente SDR (Sales Development Representative) de Academia Tesla.
Migrado a LangChain + LangGraph (create_react_agent).
"""
import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from tools.langchain_tools import SDR_TOOLS
from tools.logger import get_logger

load_dotenv()

log = get_logger("SDR")

SYSTEM_PROMPT = """Eres el Agente SDR (Sales Development Representative) de Academia Tesla, un centro preuniversitario peruano.
Tu rol: calificar prospectos, identificar el grado del alumno, recomendar el ciclo adecuado y registrar el lead en CRM.

PROCESO OBLIGATORIO:
1. Identifica el grado escolar del alumno (cepu, 5to_secundaria, 4to_secundaria, repaso, pre_universitario)
2. Llama a `consultar_ciclos` con ese grado para obtener opciones reales de Supabase
3. Recomienda el ciclo más adecuado mostrando: nombre, precio en soles, horario, modalidad y fecha de inicio
4. Al momento de recomendar un ciclo, DEBES llamar proactivamente a `enviar_horario_pdf` con el código del ciclo y el teléfono del prospecto para enviarle el horario.
5. Si el prospecto muestra interés, llama a `registrar_lead` con sus datos

TONO: Español peruano profesional. Amable y directo. Usa "usted" con apoderados. Emojis moderados: 🎓 📚 ✅
RESTRICCIÓN: Nunca inventes precios ni horarios. Solo usa datos de `consultar_ciclos`."""

# LLM para el sub-agente SDR
_llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
)

# Agente ReAct precompilado
sdr_agent = create_react_agent(
    model=_llm,
    tools=SDR_TOOLS,
    prompt=SYSTEM_PROMPT,
)


async def run_sdr_agent(
    consulta: str,
    historial: list = None,
    session_id: str = None,
    telefono: str = None,
) -> str:
    """
    Ejecuta el agente SDR con ReAct (LangGraph).
    Retorna la respuesta final como string.
    """
    from langchain_core.messages import HumanMessage, AIMessage

    sid = session_id or "-"
    log.info(f"[SDR] sid={sid} | START | consulta={consulta[:120]}")

    # Construir mensajes de entrada
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

    # Inyectar teléfono en la consulta para que el agente lo tenga disponible
    consulta_con_contexto = consulta
    if telefono:
        consulta_con_contexto = f"[Teléfono del prospecto: {telefono}]\n\n{consulta}"

    messages.append(HumanMessage(content=consulta_con_contexto))

    try:
        result = await sdr_agent.ainvoke({"messages": messages})
        # Extraer último mensaje del asistente
        ai_messages = [m for m in result["messages"] if isinstance(m, AIMessage) and m.content]
        respuesta = ai_messages[-1].content if ai_messages else ""
        log.info(f"[SDR] sid={sid} | END | respuesta={respuesta[:200]}")
        return respuesta
    except Exception as e:
        log.error(f"[SDR] sid={sid} | EXCEPTION={e}", exc_info=True)
        return f"Error en agente SDR: {str(e)}"