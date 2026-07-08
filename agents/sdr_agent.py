from langgraph.prebuilt import create_react_agent
from core.llm import llm
from core.prompts import SDR_SYSTEM_PROMPT
from tools.supabase_client import consultar_ciclos
from tools.pipedrive_client import registrar_lead

# Herramientas del agente SDR
sdr_tools = [consultar_ciclos, registrar_lead]

# Sub-grafo compilado usando create_react_agent
sdr_agent = create_react_agent(
    model=llm,
    tools=sdr_tools,
    prompt=SDR_SYSTEM_PROMPT
)
