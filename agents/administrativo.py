import anthropic
import os
import json
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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

tools = [
    {
        "name": "validar_dni",
        "description": "Valida un DNI peruano contra RENIEC vía apis.net.pe. Retorna nombres oficiales si es válido.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dni": {"type": "string", "description": "DNI de 8 dígitos a validar"}
            },
            "required": ["dni"]
        }
    },
    {
        "name": "upsert_alumno",
        "description": "Guarda o actualiza el registro del alumno en Supabase. Solo llamar si ambos DNIs son válidos.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dni_alumno": {"type": "string"},
                "nombres": {"type": "string"},
                "apellidos": {"type": "string"},
                "grado": {"type": "string"},
                "apoderado_nombre": {"type": "string"},
                "apoderado_dni": {"type": "string"},
                "apoderado_telefono": {"type": "string"},
                "ciclo_codigo": {"type": "string"},
                "estado": {"type": "string", "description": "Siempre 'Registrado'"}
            },
            "required": [
                "dni_alumno", "nombres", "apellidos", "grado",
                "apoderado_nombre", "apoderado_dni", "apoderado_telefono",
                "ciclo_codigo", "estado"
            ]
        }
    }
]


def ejecutar_tool(nombre: str, inputs: dict):
    """Despacha la ejecución de tools del agente Administrativo."""
    from tools.reniec import validar_dni
    from tools.supabase_client import upsert_alumno

    if nombre == "validar_dni":
        return validar_dni(inputs["dni"])
    if nombre == "upsert_alumno":
        return upsert_alumno(inputs)
    return {"error": f"Tool '{nombre}' no reconocida"}


def run_admin_agent(datos: str, historial: list = []) -> str:
    """
    Ejecuta el agente Administrativo con loop completo de tool_use.
    Recibe los datos del alumno/apoderado y retorna resultado de validación.
    """
    messages = historial + [{"role": "user", "content": datos}]

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
