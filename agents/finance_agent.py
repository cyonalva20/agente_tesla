from langgraph.prebuilt import create_react_agent
from core.llm import llm
from core.prompts import FINANCIERO_SYSTEM_PROMPT
from tools.stripe_client import verificar_pago
from tools.pdf_generator import generar_constancia
from tools.supabase_client import actualizar_estado_alumno, obtener_alumno_por_id, consultar_ciclo_por_codigo
from tools.evolution_whatsapp import enviar_documento, enviar_mensaje

# Herramientas del agente Financiero
finance_tools = [
    verificar_pago,
    generar_constancia,
    actualizar_estado_alumno,
    obtener_alumno_por_id,
    consultar_ciclo_por_codigo,
    enviar_documento,
    enviar_mensaje
]

# Sub-grafo compilado
finance_agent = create_react_agent(
    model=llm,
    tools=finance_tools,
    state_modifier=FINANCIERO_SYSTEM_PROMPT
)
