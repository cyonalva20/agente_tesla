from langgraph.prebuilt import create_react_agent
from core.llm import llm
from core.prompts import ADMINISTRATIVO_SYSTEM_PROMPT
from tools.reniec import validar_dni
from tools.supabase_client import upsert_alumno
from tools.stripe_client import generar_link_pago

# Herramientas del agente Administrativo
admin_tools = [validar_dni, upsert_alumno, generar_link_pago]

# Sub-grafo compilado
admin_agent = create_react_agent(
    model=llm,
    tools=admin_tools,
    prompt=ADMINISTRATIVO_SYSTEM_PROMPT
)
