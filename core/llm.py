import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv()

# Instancia global del modelo para reuso
llm = ChatAnthropic(
    model="claude-sonnet-5",
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# Modelo más rápido para tareas sencillas o planeación
llm_haiku = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    temperature=0,
    api_key=os.getenv("ANTHROPIC_API_KEY")
)
