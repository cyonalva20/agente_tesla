import anthropic
import os
import json
import uuid
import time
from dotenv import load_dotenv
from agents.sdr import run_sdr_agent
from agents.administrativo import run_admin_agent
from agents.financiero import run_financiero_agent
from tools.supabase_client import actualizar_estado_alumno
from tools.evolution_whatsapp import enviar_mensaje
from tools.logger import get_logger

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
log = get_logger("ORCH")

MAX_TOOL_ROUNDS = 10

SYSTEM_PROMPT_ORQUESTADOR = """
Eres el Orquestador de Matrículas de Academia Tesla. Coordinas 3 sub-agentes especializados para guiar al prospecto desde el primer contacto hasta la matrícula completa.

## TUS SUB-AGENTES (invócalos como tools)
- `agente_sdr` → Captación: informa ciclos, precios, horarios y registra el lead
- `agente_administrativo` → Registro: valida DNI vía RENIEC y guarda datos del alumno
- `agente_financiero` → Cierre: verifica pago Stripe y emite constancia PDF por WhatsApp

## FASES DEL EMBUDO (FSM)
Determina la fase según el contexto de la conversación:

[FASE:CAPTACION] → Usuario nuevo o preguntando por ciclos/precios/horarios
  Acción: invocar agente_sdr con la consulta del usuario

[FASE:REGISTRO] → Usuario confirmó el ciclo y está listo para inscribirse
  Acción: invocar agente_administrativo con los datos del formulario
  Requisito: necesitas dni_alumno, nombres, apellidos, grado, apoderado_nombre, apoderado_dni, apoderado_telefono, ciclo_codigo

[FASE:CIERRE] → Usuario indica que ya realizó el pago y proporciona el charge_id
  Acción: invocar agente_financiero con el charge_id y alumno_id

[FASE:ESCALAR] → Anomalía detectada (3+ intentos fallidos, datos inconsistentes, queja)
  Acción: NO invocar sub-agentes. Retornar mensaje de escalamiento con resumen de la anomalía.

## REGLAS CRÍTICAS
- Mantén contexto acumulado de la sesión: guarda dni_alumno, ciclo_codigo, alumno_id, charge_id conforme se van obteniendo
- Nunca pidas información que ya tienes en el historial
- Ante 3 fallos consecutivos de cualquier tipo → [FASE:ESCALAR]
- Tono: Español peruano profesional, amable y directo
- Mensajes máx 3 párrafos por turno
- Emojis moderados: 🎓 📚 ✅ 💳 📄
"""

TOOLS_ORQUESTADOR = [
    {
        "name": "agente_sdr",
        "description": "Sub-agente de Ventas. Invócalo en fase CAPTACION para informar sobre ciclos académicos, precios, horarios y registrar leads. Envíale la consulta del prospecto con contexto.",
        "input_schema": {
            "type": "object",
            "properties": {
                "consulta": {
                    "type": "string",
                    "description": "Consulta o contexto completo del prospecto que debe procesar el SDR"
                }
            },
            "required": ["consulta"]
        }
    },
    {
        "name": "agente_administrativo",
        "description": "Sub-agente Administrativo. Invócalo en fase REGISTRO cuando tengas todos los datos del alumno y apoderado para validar DNI y registrar en Supabase.",
        "input_schema": {
            "type": "object",
            "properties": {
                "datos": {
                    "type": "string",
                    "description": "JSON string con todos los datos del alumno: dni_alumno, nombres, apellidos, grado, apoderado_nombre, apoderado_dni, apoderado_telefono, ciclo_codigo"
                }
            },
            "required": ["datos"]
        }
    },
    {
        "name": "agente_financiero",
        "description": "Sub-agente Financiero. Invócalo en fase CIERRE cuando el usuario proporcione el charge_id de Stripe para verificar pago y emitir constancia.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instruccion": {
                    "type": "string",
                    "description": "Instrucción completa con charge_id, alumno_id y telefono_apoderado para procesar el cierre"
                }
            },
            "required": ["instruccion"]
        }
    }
]


class Orchestrator:
    def __init__(self):
        self.historial = []
        self.session_data = {
            "fase": "CAPTACION",
            "dni_alumno": None,
            "ciclo_codigo": None,
            "alumno_id": None,
            "charge_id": None,
            "intentos_fallidos": 0,
            "session_id": str(uuid.uuid4()),
            "telefono": None
        }

    def _truncar_historial(self):
        """Mantiene máximo 15 mensajes en el historial, eliminando los más viejos."""
        if len(self.historial) > 15:
            self.historial = self.historial[-15:]
            # Asegurar que el primer mensaje sea de rol "user"
            while self.historial and self.historial[0]["role"] != "user":
                self.historial.pop(0)

    def _build_system_prompt(self) -> str:
        """Construye el system prompt inyectando los datos acumulados de la sesión."""
        context = f"""
## DATOS ACUMULADOS DE ESTA SESIÓN (no los vuelvas a pedir):
- Fase actual: {self.session_data['fase']}
- DNI alumno: {self.session_data['dni_alumno'] or 'Aún no proporcionado'}
- Ciclo seleccionado: {self.session_data['ciclo_codigo'] or 'Aún no seleccionado'}
- ID alumno en BD: {self.session_data['alumno_id'] or 'No registrado aún'}
- Charge ID (Stripe): {self.session_data['charge_id'] or 'No proporcionado'}
- Intentos fallidos consecutivos: {self.session_data['intentos_fallidos']}
- Session ID: {self.session_data['session_id']}
"""
        return SYSTEM_PROMPT_ORQUESTADOR + context

    def _extraer_datos_de_resultado(self, tool_name: str, result_str: str):
        """Extrae y actualiza session_data a partir de los resultados de los sub-agentes."""
        try:
            # Intentar parsear JSON del resultado
            if '"alumno_id"' in result_str:
                # Buscar alumno_id en el resultado
                import re
                match = re.search(r'"alumno_id"\s*:\s*"([^"]+)"', result_str)
                if match:
                    self.session_data["alumno_id"] = match.group(1)

            if '"ciclo_codigo"' in result_str or '"ciclo"' in result_str:
                import re
                match = re.search(r'"ciclo_codigo"\s*:\s*"([^"]+)"', result_str)
                if match:
                    self.session_data["ciclo_codigo"] = match.group(1)

            if '"dni_alumno"' in result_str or '"dni"' in result_str:
                import re
                match = re.search(r'"dni_alumno"\s*:\s*"([^"]+)"', result_str)
                if match:
                    self.session_data["dni_alumno"] = match.group(1)

            if '"charge_id"' in result_str:
                import re
                match = re.search(r'"charge_id"\s*:\s*"([^"]+)"', result_str)
                if match:
                    self.session_data["charge_id"] = match.group(1)

            # Detectar fase de escalamiento
            if "[FASE:ESCALAR]" in result_str:
                self.session_data["fase"] = "ESCALAR"

            # Actualizar fase según el agente invocado exitosamente
            if tool_name == "agente_sdr" and '"valido": true' not in result_str.lower():
                # Si el SDR respondió, podríamos pasar a registro si hay datos suficientes
                pass
            if tool_name == "agente_administrativo" and '"valido": true' in result_str.lower():
                self.session_data["fase"] = "CIERRE"
                self.session_data["intentos_fallidos"] = 0
            if tool_name == "agente_financiero" and "constancia" in result_str.lower():
                self.session_data["fase"] = "COMPLETADO"
                self.session_data["intentos_fallidos"] = 0

            # Detectar fallos
            if '"error"' in result_str or '"valido": false' in result_str.lower():
                self.session_data["intentos_fallidos"] += 1
                if self.session_data["intentos_fallidos"] >= 3:
                    self.session_data["fase"] = "ESCALAR"
            else:
                self.session_data["intentos_fallidos"] = 0

        except Exception as e:
            log.warning(f"[ORCH] sid={self.session_data['session_id']} | _extraer_datos error={e}")

    def _ejecutar_sub_agente(self, tool_name: str, inputs: dict) -> str:
        """Ejecuta el sub-agente correspondiente y retorna su resultado."""
        contexto = self.historial[-6:] if len(self.historial) > 6 else []
        sid = self.session_data["session_id"]
        inputs_log = json.dumps(inputs, ensure_ascii=False, default=str)[:300]
        log.info(f"[ORCH] sid={sid} | → {tool_name} | fase={self.session_data['fase']} | input={inputs_log}")
        t0 = time.monotonic()

        try:
            if tool_name == "agente_sdr":
                result = run_sdr_agent(inputs["consulta"], contexto, session_id=sid, telefono=self.session_data.get("telefono"))
            elif tool_name == "agente_administrativo":
                result = run_admin_agent(inputs["datos"], contexto, session_id=sid)
            elif tool_name == "agente_financiero":
                result = run_financiero_agent(inputs["instruccion"], contexto, session_id=sid)
            else:
                result = json.dumps({"error": f"Sub-agente '{tool_name}' no reconocido"})

            ms = int((time.monotonic() - t0) * 1000)
            if '"error"' in result:
                log.warning(f"[ORCH] sid={sid} | ← {tool_name} | contiene error | {ms}ms | {result[:300]}")
            else:
                log.info(f"[ORCH] sid={sid} | ← {tool_name} | OK {len(result)} chars | {ms}ms")

            self._extraer_datos_de_resultado(tool_name, result)
            return result

        except Exception as e:
            ms = int((time.monotonic() - t0) * 1000)
            self.session_data["intentos_fallidos"] += 1
            error_msg = json.dumps({"error": f"Error en {tool_name}: {str(e)}"})
            log.error(f"[ORCH] sid={sid} | ← {tool_name} | EXCEPTION={e} | {ms}ms", exc_info=True)
            if self.session_data["intentos_fallidos"] >= 3:
                self.session_data["fase"] = "ESCALAR"
            return error_msg

    async def procesar_mensaje(self, mensaje_usuario: str) -> str:
        """
        Procesa un mensaje del usuario a través del orquestador.
        Loop completo: modelo → tool_use → sub-agente → tool_result → respuesta final.
        """
        # 1. Agregar mensaje del usuario al historial
        self.historial.append({"role": "user", "content": mensaje_usuario})
        self._truncar_historial()

        # 2. Si estamos en ESCALAR, no invocar sub-agentes
        if self.session_data["fase"] == "ESCALAR":
            respuesta_escalar = (
                "⚠️ **Caso escalado a atención humana**\n\n"
                "Se han detectado múltiples intentos fallidos en esta sesión. "
                "Un asesor humano revisará su caso a la brevedad.\n\n"
                f"📋 **Session ID:** {self.session_data['session_id']}\n"
                f"📄 **Datos registrados:** DNI: {self.session_data.get('dni_alumno', 'N/A')}, "
                f"Ciclo: {self.session_data.get('ciclo_codigo', 'N/A')}\n\n"
                "Por favor, comuníquese al 📞 (01) 555-0100 o espere a que un asesor lo contacte."
            )
            self.historial.append({"role": "assistant", "content": respuesta_escalar})
            return respuesta_escalar

        # 3. Loop del orquestador con tool_use
        sid = self.session_data["session_id"]
        log.info(f"[ORCH] sid={sid} | MENSAJE | fase={self.session_data['fase']} | msg={mensaje_usuario[:120]}")
        messages = list(self.historial)
        rounds = 0

        while True:
            rounds += 1
            if rounds > MAX_TOOL_ROUNDS:
                log.error(f"[ORCH] sid={sid} | MAX_TOOL_ROUNDS={MAX_TOOL_ROUNDS} excedido")
                return "Error: demasiadas iteraciones internas. Por favor contacte soporte."

            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=self._build_system_prompt(),
                tools=TOOLS_ORQUESTADOR,
                messages=messages
            )

            # Si el modelo terminó de responder directamente
            if response.stop_reason == "end_turn":
                respuesta_final = next(
                    (b.text for b in response.content if b.type == "text"),
                    ""
                )
                self.historial.append({"role": "assistant", "content": respuesta_final})
                self._detectar_fase_por_contenido(respuesta_final)
                log.info(f"[ORCH] sid={sid} | RESPUESTA | fase={self.session_data['fase']} | {respuesta_final[:150]}")
                return respuesta_final

            # Procesar tool_use
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    # Actualizar fase según el tool invocado
                    if block.name == "agente_sdr":
                        self.session_data["fase"] = "CAPTACION"
                    elif block.name == "agente_administrativo":
                        self.session_data["fase"] = "REGISTRO"
                    elif block.name == "agente_financiero":
                        self.session_data["fase"] = "CIERRE"

                    result = self._ejecutar_sub_agente(block.name, block.input)

                    # Verificar si debemos escalar
                    if self.session_data["fase"] == "ESCALAR":
                        escalar_msg = (
                            "⚠️ Se han detectado múltiples fallos consecutivos. "
                            "Este caso ha sido escalado a atención humana. "
                            f"Session ID: {self.session_data['session_id']}"
                        )
                        self.historial.append({"role": "assistant", "content": escalar_msg})
                        return escalar_msg

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

            messages.append({"role": "user", "content": tool_results})

    def _detectar_fase_por_contenido(self, respuesta: str):
        """Detecta cambios de fase implícitos en la respuesta del orquestador."""
        respuesta_lower = respuesta.lower()
        if any(kw in respuesta_lower for kw in ["datos del alumno", "dni del alumno", "registrar", "formulario"]):
            if self.session_data["fase"] == "CAPTACION":
                self.session_data["fase"] = "REGISTRO"
        if any(kw in respuesta_lower for kw in ["charge_id", "pago", "stripe", "comprobante"]):
            if self.session_data["fase"] == "REGISTRO":
                self.session_data["fase"] = "CIERRE"
        if "[fase:escalar]" in respuesta_lower:
            self.session_data["fase"] = "ESCALAR"
