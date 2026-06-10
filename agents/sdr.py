import anthropic
import os
import json
import time
from dotenv import load_dotenv
from tools.logger import get_logger
from anthropic._exceptions import OverloadedError, RateLimitError

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
log = get_logger("SDR")

SYSTEM_PROMPT = """Eres el Agente SDR (Sales Development Representative) de Academia Tesla, un centro preuniversitario peruano.
Tu rol: calificar prospectos, identificar el grado del alumno, recomendar el ciclo adecuado y registrar el lead en CRM.

PROCESO OBLIGATORIO:
1. Identifica el grado escolar del alumno (cepu, 5to_secundaria, 4to_secundaria, repaso, pre_universitario)
2. Llama a `consultar_ciclos` con ese grado para obtener opciones reales de Supabase
3. Recomienda el ciclo más adecuado mostrando: nombre, precio en soles, horario, modalidad y fecha de inicio
4. Al momento de recomendar un ciclo, DEBES llamar proactivamente a `enviar_horario_pdf` con el código del ciclo para enviarle el horario.
5. Si el prospecto muestra interés, llama a `registrar_lead` con sus datos

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
                    "description": (
                        "Grado del alumno. Valores válidos: "
                        "cepu, 5to_secundaria, 4to_secundaria, repaso, pre_universitario"
                    )
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
                "nombre_apoderado": {
                    "type": "string",
                    "description": "Nombre completo del apoderado"
                },
                "telefono": {
                    "type": "string",
                    "description": "WhatsApp con formato +51XXXXXXXXX"
                },
                "grado": {
                    "type": "string",
                    "description": "Grado escolar del alumno en formato canónico, ej: 5to_secundaria"
                },
                "ciclo_recomendado": {
                    "type": "string",
                    "description": "Código del ciclo recomendado, ej: G-SEC5-2025-B"
                }
            },
            "required": ["nombre_apoderado", "telefono", "grado", "ciclo_recomendado"]
        }
    },
    {
        "name": "enviar_horario_pdf",
        "description": "Envía el horario del ciclo en formato PDF proactivamente por WhatsApp. Úsalo SIEMPRE que recomiendes un ciclo específico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ciclo_codigo": {
                    "type": "string",
                    "description": "Código del ciclo del cual se enviará el horario, ej: G-SEC5-2025-B"
                }
            },
            "required": ["ciclo_codigo"]
        }
    }
]


def ejecutar_tool(nombre: str, inputs: dict, session_id: str = None, telefono: str = None):
    """Despacha la ejecución de tools del agente SDR."""
    from tools.supabase_client import consultar_ciclos, normalizar_grado
    from tools.pipedrive_client import registrar_lead
    from tools.horarios import obtener_url_horario
    from tools.evolution_whatsapp import enviar_documento

    sid = session_id or "-"
    inputs_log = json.dumps(inputs, ensure_ascii=False, default=str)[:300]
    log.info(f"[SDR] sid={sid} | tool={nombre} | input={inputs_log}")
    t0 = time.monotonic()

    if nombre == "consultar_ciclos":
        grado = normalizar_grado(inputs["grado"])
        result = consultar_ciclos(grado)
    elif nombre == "registrar_lead":
        result = registrar_lead(
            inputs["nombre_apoderado"],
            inputs["telefono"],
            inputs["grado"],
            inputs["ciclo_recomendado"]
        )
    elif nombre == "enviar_horario_pdf":
        url_pdf = obtener_url_horario(inputs["ciclo_codigo"])
        if not url_pdf:
            result = {"error": "No se pudo generar la URL del horario"}
        elif not telefono:
            result = {"error": "No hay teléfono en la sesión para enviar el horario"}
        else:
            caption = f"Aquí tienes el horario detallado del ciclo {inputs['ciclo_codigo']} 📅"
            res = enviar_documento(telefono, url_pdf, caption)
            if res.get("enviado"):
                result = {"status": "ok", "mensaje": "Horario en PDF enviado exitosamente al prospecto"}
            else:
                result = {"error": f"Fallo al enviar el PDF: {res.get('error')}"}
    else:
        result = {"error": f"Tool '{nombre}' no reconocida"}

    ms = int((time.monotonic() - t0) * 1000)
    result_log = json.dumps(result, ensure_ascii=False, default=str)[:400]
    if "error" in result:
        log.error(f"[SDR] sid={sid} | tool={nombre} | ERROR={result['error']} | {ms}ms")
    else:
        log.info(f"[SDR] sid={sid} | tool={nombre} | OK={result_log} | {ms}ms")

    return result




def _llamar_anthropic_con_retry(client, max_reintentos: int = 3, **kwargs):
    for intento in range(max_reintentos):
        try:
            return client.messages.create(**kwargs)
        except OverloadedError:                        # ✅ sin anthropic.
            if intento == max_reintentos - 1:
                raise
            espera = 2 ** (intento + 1)
            print(f"[SDR] API sobrecargada, reintento {intento + 1}/{max_reintentos} en {espera}s...")
            time.sleep(espera)
        except RateLimitError:                         # ✅ sin anthropic.
            if intento == max_reintentos - 1:
                raise
            espera = 2 ** (intento + 2)
            print(f"[SDR] Rate limit, reintento {intento + 1}/{max_reintentos} en {espera}s...")
            time.sleep(espera)


def run_sdr_agent(
    consulta: str,
    historial: list = None,
    session_id: str = None,
    telefono: str = None
) -> str:
    historial = historial or []
    messages = historial + [{"role": "user", "content": consulta}]

    while True:
        # ✅ Reemplaza client.messages.create(...) por esto:
        response = _llamar_anthropic_con_retry(
            client,
            max_reintentos=3,
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            return next(
                (b.text for b in response.content if b.type == "text"),
                ""
            )

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    result = ejecutar_tool(block.name, block.input, session_id=session_id, telefono=telefono)
                except ValueError as e:
                    result = {"error": str(e)}
                except Exception as e:
                    result = {"error": f"Error interno al ejecutar '{block.name}': {str(e)}"}

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result, ensure_ascii=False, default=str)
                })

        messages.append({"role": "user", "content": tool_results})