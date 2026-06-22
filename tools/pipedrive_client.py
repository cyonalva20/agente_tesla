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
    """
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
        person_data = person_response.json()

        if not person_data.get("success"):
            return {"error": f"Error al crear persona: {person_data.get('error', 'Unknown')}"}

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
            return {"error": f"Error al crear lead: {lead_data.get('error', 'Unknown')}"}

        return {
            "lead_id": lead_data["data"]["id"],
            "person_id": person_id
        }
    except requests.RequestException as e:
        return {"error": f"Error de conexión con Pipedrive: {str(e)}"}
