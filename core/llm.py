import os
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv()

# Instancia global del modelo para reuso
llm = ChatAnthropic(
    model="claude-3-5-sonnet-20241022", # Se recomienda un modelo moderno
    temperature=0,
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

# Modelo más rápido para tareas sencillas o planeación
llm_haiku = ChatAnthropic(
    model="claude-3-5-haiku-20241022",
    temperature=0,
    api_key=os.getenv("ANTHROPIC_API_KEY")
)
