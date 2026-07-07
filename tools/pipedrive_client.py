import os
import requests
from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

PIPEDRIVE_API_TOKEN = os.getenv("PIPEDRIVE_API_TOKEN")
PIPEDRIVE_DOMAIN = os.getenv("PIPEDRIVE_DOMAIN")

BASE_URL = f"https://{PIPEDRIVE_DOMAIN}.pipedrive.com/api/v1"

@tool
def registrar_lead(nombre_apoderado: str, telefono: str, grado: str, ciclo_recomendado: str) -> dict:
    """
    Registra un lead en Pipedrive CRM.
    1. POST /persons — Crea persona con nombre y teléfono.
    2. POST /leads — Crea lead con título "{nombre_apoderado} - {grado}" y person_id.
    Retorna {"lead_id": ..., "person_id": ...}
    
    IMPORTANTE: Si falla el registro en CRM (p.ej. por credenciales inválidas),
    retorna un dict con "registrado": False. Esto NO impide que el flujo de
    matrícula continúe — los datos del prospecto ya están en la conversación.
    """
    if not PIPEDRIVE_API_TOKEN or not PIPEDRIVE_DOMAIN:
        return {
            "registrado": False,
            "motivo": "Credenciales de Pipedrive no configuradas. El lead no fue registrado en CRM, pero los datos del prospecto están guardados en la conversación.",
            "datos_capturados": {
                "nombre_apoderado": nombre_apoderado,
                "telefono": telefono,
                "grado": grado,
                "ciclo_recomendado": ciclo_recomendado
            }
        }
    
    try:
        # Paso 1: Crear persona
        person_payload = {
            "name": nombre_apoderado,
            "phone": [{"value": telefono, "primary": True}]
        }
        person_response = requests.post(
            f"{BASE_URL}/persons?api_token={PIPEDRIVE_API_TOKEN}",
            json=person_payload,
            timeout=10
        )
        
        if person_response.status_code == 401:
            return {
                "registrado": False,
                "motivo": "Token de Pipedrive expirado o inválido (HTTP 401). El lead no fue registrado en CRM, pero los datos del prospecto están capturados.",
                "datos_capturados": {
                    "nombre_apoderado": nombre_apoderado,
                    "telefono": telefono,
                    "grado": grado,
                    "ciclo_recomendado": ciclo_recomendado
                }
            }
        
        person_data = person_response.json()

        if not person_data.get("success"):
            return {
                "registrado": False,
                "motivo": f"Error al crear persona en Pipedrive: {person_data.get('error', 'Unknown')}",
                "datos_capturados": {
                    "nombre_apoderado": nombre_apoderado,
                    "telefono": telefono,
                    "grado": grado,
                    "ciclo_recomendado": ciclo_recomendado
                }
            }

        person_id = person_data["data"]["id"]

        # Paso 2: Crear lead
        lead_payload = {
            "title": f"{nombre_apoderado} - {grado}",
            "person_id": person_id
        }
        lead_response = requests.post(
            f"{BASE_URL}/leads?api_token={PIPEDRIVE_API_TOKEN}",
            json=lead_payload,
            timeout=10
        )
        lead_data = lead_response.json()

        if not lead_data.get("success"):
            return {
                "registrado": False,
                "motivo": f"Error al crear lead en Pipedrive: {lead_data.get('error', 'Unknown')}",
                "person_id": person_id,
                "datos_capturados": {
                    "nombre_apoderado": nombre_apoderado,
                    "telefono": telefono,
                    "grado": grado,
                    "ciclo_recomendado": ciclo_recomendado
                }
            }

        return {
            "registrado": True,
            "lead_id": lead_data["data"]["id"],
            "person_id": person_id
        }
    except requests.RequestException as e:
        return {
            "registrado": False,
            "motivo": f"Error de conexión con Pipedrive: {str(e)}",
            "datos_capturados": {
                "nombre_apoderado": nombre_apoderado,
                "telefono": telefono,
                "grado": grado,
                "ciclo_recomendado": ciclo_recomendado
            }
        }
