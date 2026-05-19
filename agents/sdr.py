import anthropic
import os
import json
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """Eres el Agente SDR (Sales Development Representative) de Academia Tesla, un centro preuniversitario peruano.
Tu rol: calificar prospectos, identificar el grado del alumno, recomendar el ciclo adecuado y registrar el lead en CRM.

PROCESO OBLIGATORIO:
1. Identifica el grado escolar del alumno (cepu, 5to_secundaria, 4to_secundaria, repaso, pre_universitario)
2. Llama a `consultar_ciclos` con ese grado para obtener opciones reales de Supabase
3. Recomienda el ciclo más adecuado mostrando: nombre, precio en soles, horario, modalidad y fecha de inicio
4. Si el prospecto muestra interés, llama a `registrar_lead` con sus datos

TONO: Español peruano profesional. Amable y directo. Usa "usted" con apoderados. Emojis moderados: 🎓 📚 ✅
RESTRICCIÓN: Nunca inventes precios ni horarios. Solo usa datos de `consultar_ciclos`."""

tools = [
    {
        "name": "consultar_ciclos",
        "description": "Consulta los ciclos académicos disponibles en Supabase filtrados por grado escolar. Úsalo SIEMPRE antes de recomendar cualquier ciclo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "grado": {
                    "type": "string",
                    "description": "Grado del alumno. Valores válidos: cepu, 5to_secundaria, 4to_secundaria, repaso, pre_universitario"
                }
            },
            "required": ["grado"]
        }
    },
    {
        "name": "registrar_lead",
        "description": "Registra el prospecto en Pipedrive CRM cuando muestra interés concreto en matricularse.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_apoderado": {"type": "string", "description": "Nombre completo del apoderado"},
                "telefono": {"type": "string", "description": "WhatsApp con formato +51XXXXXXXXX"},
                "grado": {"type": "string", "description": "Grado escolar del alumno"},
                "ciclo_recomendado": {"type": "string", "description": "Código del ciclo recomendado, ej: G-SEC5-2025-B"}
            },
            "required": ["nombre_apoderado", "telefono", "grado", "ciclo_recomendado"]
        }
    }
]


def ejecutar_tool(nombre: str, inputs: dict):
    """Despacha la ejecución de tools del agente SDR."""
    from tools.supabase_client import consultar_ciclos
    from tools.pipedrive_client import registrar_lead

    if nombre == "consultar_ciclos":
        return consultar_ciclos(inputs["grado"])
    if nombre == "registrar_lead":
        return registrar_lead(
            inputs["nombre_apoderado"],
            inputs["telefono"],
            inputs["grado"],
            inputs["ciclo_recomendado"]
        )
    return {"error": f"Tool '{nombre}' no reconocida"}


def run_sdr_agent(consulta: str, historial: list = []) -> str:
    """
    Ejecuta el agente SDR con loop completo de tool_use.
    Recibe la consulta del prospecto y retorna la respuesta final.
    """
    messages = historial + [{"role": "user", "content": consulta}]

    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages
        )

        # Si el modelo terminó de responder, extraer texto final
        if response.stop_reason == "end_turn":
            return next(
                (b.text for b in response.content if b.type == "text"),
                ""
            )

        # Procesar tool_use: agregar respuesta del asistente
        messages.append({"role": "assistant", "content": response.content})

        # Ejecutar cada tool y recopilar resultados
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = ejecutar_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str)
                })

        # Enviar resultados de tools al modelo
        messages.append({"role": "user", "content": tool_results})
