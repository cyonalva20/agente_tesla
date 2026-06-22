import anthropic
import os
import json
import time
from dotenv import load_dotenv
from tools.logger import get_logger

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
log = get_logger("FIN")

SYSTEM_PROMPT = """Eres el Agente Financiero de Academia Tesla. Tu rol: verificar pagos y emitir constancias de matrícula oficiales.

REGLA DE ORO — ABSOLUTA E INNEGOCIABLE:
NUNCA generes una constancia de matrícula si el estado del pago no es exactamente "paid".
Si el pago falla, informa el error y sugiere intentar nuevamente o escalar a atención humana.

PROCESO:
1. Llama a `verificar_pago` con el charge_id proporcionado
2. Si status == "paid":
   a. Llama a `generar_constancia` con alumno_id y ciclo_codigo
   b. Llama a `actualizar_estado` con nuevo_estado="Matriculado" y metadata con constancia_numero y pdf_url
   c. Llama a `enviar_whatsapp` para notificar al apoderado con el PDF
   d. Retorna confirmación con número de constancia
3. Si status != "paid": retorna el error sin ejecutar ningún paso más

ESCALAMIENTO: Si el pago falla 3 veces, indica explícitamente [FASE:ESCALAR] en tu respuesta."""

tools = [
    {
        "name": "verificar_pago",
        "description": "Verifica el estado de un pago en Stripe. Retorna status: paid/failed/pending.",
        "input_schema": {
            "type": "object",
            "properties": {
                "charge_id": {
                    "type": "string",
                    "description": "ID del PaymentIntent o Charge de Stripe (pi_... o ch_...)"
                }
            },
            "required": ["charge_id"]
        }
    },
    {
        "name": "generar_constancia",
        "description": "Genera el PDF de la constancia de matrícula con QR y lo sube a Supabase Storage. Solo llamar si el pago es 'paid'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alumno_id":   {"type": "string", "description": "UUID del alumno en Supabase"},
                "ciclo_codigo": {"type": "string", "description": "Código del ciclo, ej: G-SEC5-2025-B"}
            },
            "required": ["alumno_id", "ciclo_codigo"]
        }
    },
    {
        "name": "actualizar_estado",
        "description": "Actualiza el estado del alumno a Matriculado en Supabase y registra en historial_estados.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alumno_id":    {"type": "string"},
                "nuevo_estado": {"type": "string", "description": "Siempre 'Matriculado'"},
                "metadata": {
                    "type": "object",
                    "description": "Incluir constancia_numero, pdf_url, monto_pagado"
                }
            },
            "required": ["alumno_id", "nuevo_estado"]
        }
    },
    {
        "name": "enviar_whatsapp",
        "description": "Envía la constancia por WhatsApp al apoderado vía Evolution API.",
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {"type": "string", "description": "WhatsApp del apoderado formato +51XXXXXXXXX"},
                "pdf_url":  {"type": "string", "description": "URL pública del PDF generado"},
                "mensaje":  {"type": "string", "description": "Mensaje de confirmación en español peruano"}
            },
            "required": ["telefono", "pdf_url", "mensaje"]
        }
    }
]


def ejecutar_tool(nombre: str, inputs: dict, session_id: str = None):
    """Despacha la ejecución de tools del agente Financiero."""
    from tools.stripe_client import verificar_pago
    from tools.pdf_generator import generar_constancia
    from tools.supabase_client import (
        actualizar_estado_alumno,
        obtener_alumno_por_id,
        consultar_ciclo_por_codigo,
    )
    from tools.evolution_whatsapp import enviar_documento

    sid = session_id or "-"
    inputs_log = json.dumps(inputs, ensure_ascii=False, default=str)[:300]
    log.info(f"[FIN] sid={sid} | tool={nombre} | input={inputs_log}")
    t0 = time.monotonic()

    try:
        if nombre == "verificar_pago":
            result = verificar_pago(inputs["charge_id"])

        elif nombre == "generar_constancia":
            alumno = obtener_alumno_por_id(inputs["alumno_id"])
            ciclo  = consultar_ciclo_por_codigo(inputs["ciclo_codigo"])

            if not alumno:
                result = {"error": "Alumno no encontrado"}
            elif not ciclo:
                result = {"error": "Ciclo no encontrado"}
            else:
                # generar_constancia ahora retorna dict:
                # { archivo_local, url_publica, constancia_numero, error? }
                gen = generar_constancia(alumno, ciclo)

                if "error" in gen:
                    # El PDF se generó localmente pero falló el upload a Supabase
                    log.warning(
                        f"[FIN] sid={sid} | generar_constancia upload fallido: {gen['error']}"
                    )

                result = {
                    "pdf_url":           gen.get("url_publica") or gen.get("archivo_local"),
                    "constancia_numero": gen["constancia_numero"],
                    "archivo_local":     gen["archivo_local"],
                }
                if "error" in gen:
                    result["upload_warning"] = gen["error"]

        elif nombre == "actualizar_estado":
            result = actualizar_estado_alumno(
                inputs["alumno_id"],
                inputs["nuevo_estado"],
                inputs.get("metadata", {})
            )

        elif nombre == "enviar_whatsapp":
            result = enviar_documento(
                inputs["telefono"],
                inputs["pdf_url"],
                inputs["mensaje"]
            )

        else:
            result = {"error": f"Tool '{nombre}' no reconocida"}

    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        log.error(f"[FIN] sid={sid} | tool={nombre} | EXCEPTION={e} | {ms}ms", exc_info=True)
        return {"error": f"Error interno en '{nombre}': {str(e)}"}

    ms = int((time.monotonic() - t0) * 1000)
    result_log = json.dumps(result, ensure_ascii=False, default=str)[:400]
    if "error" in result:
        log.error(f"[FIN] sid={sid} | tool={nombre} | ERROR={result['error']} | {ms}ms")
    else:
        log.info(f"[FIN] sid={sid} | tool={nombre} | OK={result_log} | {ms}ms")

    return result


def run_financiero_agent(input_text: str, historial: list = None, session_id: str = None) -> str:
    """
    Ejecuta el agente Financiero con loop completo de tool_use.
    Recibe datos de pago y retorna confirmación o error.
    """
    historial = historial or []
    sid = session_id or "-"
    log.info(f"[FIN] sid={sid} | START | input={input_text[:120]}")

    messages = historial + [{"role": "user", "content": input_text}]

    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            respuesta = next(
                (b.text for b in response.content if b.type == "text"),
                ""
            )
            log.info(f"[FIN] sid={sid} | END | respuesta={respuesta[:200]}")
            return respuesta

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                try:
                    result = ejecutar_tool(block.name, block.input, session_id=sid)
                except Exception as e:
                    result = {"error": f"Error interno al ejecutar '{block.name}': {str(e)}"}
                    log.error(
                        f"[FIN] sid={sid} | tool={block.name} | EXCEPTION={e}",
                        exc_info=True
                    )

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     json.dumps(result, ensure_ascii=False, default=str)
                })

        messages.append({"role": "user", "content": tool_results})