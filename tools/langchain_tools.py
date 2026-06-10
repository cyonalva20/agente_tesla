"""
Wrappers @tool de LangChain sobre las funciones existentes.
Los archivos originales en tools/ NO se modifican; aquí solo se envuelven.
"""
import json
from langchain_core.tools import tool

# ═══════════════════════════════════════════
#  TOOLS DEL AGENTE SDR
# ═══════════════════════════════════════════

@tool
def consultar_ciclos(grado: str) -> str:
    """Consulta los ciclos académicos disponibles en Supabase filtrados por grado escolar.
    Grados válidos: cepu, 5to_secundaria, 4to_secundaria, repaso, pre_universitario.
    Úsalo SIEMPRE antes de recomendar cualquier ciclo."""
    from tools.supabase_client import consultar_ciclos as _consultar, normalizar_grado
    try:
        grado_norm = normalizar_grado(grado)
        result = _consultar(grado_norm)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def registrar_lead(nombre_apoderado: str, telefono: str, grado: str, ciclo_recomendado: str) -> str:
    """Registra el prospecto en Pipedrive CRM cuando muestra interés concreto en matricularse.
    Parámetros: nombre_apoderado, telefono (+51XXXXXXXXX), grado (ej: 5to_secundaria), ciclo_recomendado (ej: G-SEC5-2025-B)."""
    from tools.pipedrive_client import registrar_lead as _registrar
    try:
        result = _registrar(nombre_apoderado, telefono, grado, ciclo_recomendado)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def enviar_horario_pdf(ciclo_codigo: str, telefono: str) -> str:
    """Envía el horario del ciclo en formato PDF por WhatsApp al prospecto.
    Úsalo SIEMPRE que recomiendes un ciclo específico.
    Parámetros: ciclo_codigo (ej: G-SEC5-2025-B), telefono (número del prospecto)."""
    from tools.horarios import obtener_url_horario
    from tools.evolution_whatsapp import enviar_documento
    try:
        url_pdf = obtener_url_horario(ciclo_codigo)
        if not url_pdf:
            return json.dumps({"error": "No se pudo generar la URL del horario"})
        if not telefono:
            return json.dumps({"error": "No hay teléfono para enviar el horario"})
        caption = f"Aquí tienes el horario detallado del ciclo {ciclo_codigo} 📅"
        res = enviar_documento(telefono, url_pdf, caption)
        if res.get("enviado"):
            return json.dumps({"status": "ok", "mensaje": "Horario en PDF enviado exitosamente"})
        else:
            return json.dumps({"error": f"Fallo al enviar el PDF: {res.get('error')}"})
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ═══════════════════════════════════════════
#  TOOLS DEL AGENTE ADMINISTRATIVO
# ═══════════════════════════════════════════

@tool
def validar_dni(dni: str) -> str:
    """Valida un DNI peruano de 8 dígitos contra RENIEC vía apis.net.pe.
    Retorna nombres oficiales si es válido."""
    from tools.reniec import validar_dni as _validar
    try:
        result = _validar(dni)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def upsert_alumno(
    dni_alumno: str,
    nombres: str,
    apellidos: str,
    grado: str,
    apoderado_nombre: str,
    apoderado_dni: str,
    apoderado_telefono: str,
    ciclo_codigo: str,
    estado: str = "Registrado"
) -> str:
    """Guarda o actualiza el registro del alumno en Supabase.
    Solo llamar si ambos DNIs (alumno y apoderado) fueron validados exitosamente.
    El estado inicial siempre es 'Registrado'."""
    from tools.supabase_client import upsert_alumno as _upsert
    try:
        datos = {
            "dni_alumno": dni_alumno,
            "nombres": nombres,
            "apellidos": apellidos,
            "grado": grado,
            "apoderado_nombre": apoderado_nombre,
            "apoderado_dni": apoderado_dni,
            "apoderado_telefono": apoderado_telefono,
            "ciclo_codigo": ciclo_codigo,
            "estado": estado,
        }
        result = _upsert(datos)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ═══════════════════════════════════════════
#  TOOLS DEL AGENTE FINANCIERO
# ═══════════════════════════════════════════

@tool
def verificar_pago(charge_id: str) -> str:
    """Verifica el estado de un pago en Stripe.
    Acepta PaymentIntent (pi_...) o Charge (ch_...).
    Retorna status: paid/failed/pending y monto."""
    from tools.stripe_client import verificar_pago as _verificar
    try:
        result = _verificar(charge_id)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def generar_constancia(alumno_id: str, ciclo_codigo: str) -> str:
    """Genera el PDF de la constancia de matrícula con QR y lo sube a Supabase Storage.
    Solo llamar si el pago fue verificado como 'paid'.
    Retorna pdf_url y constancia_numero."""
    from tools.supabase_client import obtener_alumno_por_id, consultar_ciclo_por_codigo
    from tools.pdf_generator import generar_constancia as _generar
    try:
        alumno = obtener_alumno_por_id(alumno_id)
        ciclo = consultar_ciclo_por_codigo(ciclo_codigo)
        if not alumno:
            return json.dumps({"error": "Alumno no encontrado"})
        if not ciclo:
            return json.dumps({"error": "Ciclo no encontrado"})
        gen = _generar(alumno, ciclo)
        result = {
            "pdf_url": gen.get("url_publica") or gen.get("archivo_local"),
            "constancia_numero": gen["constancia_numero"],
        }
        if "error" in gen:
            result["upload_warning"] = gen["error"]
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def actualizar_estado(alumno_id: str, nuevo_estado: str, constancia_numero: str = "", pdf_url: str = "", monto_pagado: str = "") -> str:
    """Actualiza el estado del alumno en Supabase y registra en historial_estados.
    Normalmente se llama con nuevo_estado='Matriculado' después de generar la constancia."""
    from tools.supabase_client import actualizar_estado_alumno
    try:
        metadata = {}
        if constancia_numero:
            metadata["constancia_numero"] = constancia_numero
        if pdf_url:
            metadata["pdf_url"] = pdf_url
        if monto_pagado:
            metadata["monto_pagado"] = monto_pagado
        result = actualizar_estado_alumno(alumno_id, nuevo_estado, metadata)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def enviar_whatsapp(telefono: str, pdf_url: str, mensaje: str) -> str:
    """Envía la constancia de matrícula en PDF por WhatsApp al apoderado vía Evolution API.
    Parámetros: telefono (+51XXXXXXXXX), pdf_url (URL pública del PDF), mensaje (texto de confirmación)."""
    from tools.evolution_whatsapp import enviar_documento
    try:
        result = enviar_documento(telefono, pdf_url, mensaje)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ═══════════════════════════════════════════
#  AGRUPACIONES POR AGENTE
# ═══════════════════════════════════════════

SDR_TOOLS = [consultar_ciclos, registrar_lead, enviar_horario_pdf]
ADMIN_TOOLS = [validar_dni, upsert_alumno]
FINANCIERO_TOOLS = [verificar_pago, generar_constancia, actualizar_estado, enviar_whatsapp]
