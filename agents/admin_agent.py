from langgraph.prebuilt import create_react_agent
from core.llm import llm
from core.prompts import ADMINISTRATIVO_SYSTEM_PROMPT
from tools.reniec import validar_dni
from tools.supabase_client import upsert_alumno

# Herramientas del agente Administrativo
admin_tools = [validar_dni, upsert_alumno]

# Sub-grafo compilado
admin_agent = create_react_agent(
    model=llm,
    tools=admin_tools,
    state_modifier=ADMINISTRATIVO_SYSTEM_PROMPT
)
