import anthropic
import os
import json
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

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
        "description": "Genera el PDF de la constancia de matrícula con QR. Solo llamar si el pago es 'paid'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alumno_id": {"type": "string", "description": "UUID del alumno en Supabase"},
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
                "alumno_id": {"type": "string"},
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
                "pdf_url": {"type": "string", "description": "URL pública del PDF generado"},
                "mensaje": {"type": "string", "description": "Mensaje de confirmación en español peruano"}
            },
            "required": ["telefono", "pdf_url", "mensaje"]
        }
    }
]


def ejecutar_tool(nombre: str, inputs: dict):
    """Despacha la ejecución de tools del agente Financiero."""
    from tools.stripe_client import verificar_pago
    from tools.pdf_generator import generar_constancia
    from tools.supabase_client import (
        actualizar_estado_alumno,
        obtener_alumno_por_id,
        consultar_ciclo_por_codigo
    )
    from tools.evolution_whatsapp import enviar_documento

    if nombre == "verificar_pago":
        return verificar_pago(inputs["charge_id"])

    if nombre == "generar_constancia":
        # Obtener datos completos de alumno y ciclo para el PDF
        alumno = obtener_alumno_por_id(inputs["alumno_id"])
        ciclo = consultar_ciclo_por_codigo(inputs["ciclo_codigo"])
        if not alumno:
            return {"error": "Alumno no encontrado"}
        if not ciclo:
            return {"error": "Ciclo no encontrado"}
        pdf_path = generar_constancia(alumno, ciclo)
        return {"pdf_url": pdf_path, "constancia_numero": os.path.basename(pdf_path).replace(".pdf", "")}

    if nombre == "actualizar_estado":
        return actualizar_estado_alumno(
            inputs["alumno_id"],
            inputs["nuevo_estado"],
            inputs.get("metadata", {})
        )

    if nombre == "enviar_whatsapp":
        return enviar_documento(
            inputs["telefono"],
            inputs["pdf_url"],
            inputs["mensaje"]
        )

    return {"error": f"Tool '{nombre}' no reconocida"}


def run_financiero_agent(input_text: str, historial: list = []) -> str:
    """
    Ejecuta el agente Financiero con loop completo de tool_use.
    Recibe datos de pago y retorna confirmación o error.
    """
    messages = historial + [{"role": "user", "content": input_text}]

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
