import os
import requests
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE")


def enviar_mensaje(telefono: str, mensaje: str) -> dict:
    """
    Envía un mensaje de texto por WhatsApp via Evolution API.
    POST {EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}
    Header: apikey: {EVOLUTION_API_KEY}
    Body: {"number": telefono, "text": mensaje}
    Retorna {"enviado": True} o {"enviado": False, "error": ...}
    """
    url = f"{EVOLUTION_API_URL}/message/sendText/{EVOLUTION_INSTANCE}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "number": telefono,
        "text": mensaje
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)

        if response.status_code in (200, 201):
            return {"enviado": True}
        else:
            return {
                "enviado": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }
    except requests.RequestException as e:
        return {
            "enviado": False,
            "error": f"Error de conexión: {str(e)}"
        }


def enviar_documento(telefono: str, pdf_url: str, caption: str) -> dict:
    """
    Envía un documento PDF por WhatsApp via Evolution API.
    POST {EVOLUTION_API_URL}/message/sendMedia/{EVOLUTION_INSTANCE}
    Body: {"number": telefono, "mediatype": "document", "media": pdf_url, "caption": caption}
    Retorna {"enviado": True} o {"enviado": False, "error": ...}
    """
    url = f"{EVOLUTION_API_URL}/message/sendMedia/{EVOLUTION_INSTANCE}"
    headers = {
        "apikey": EVOLUTION_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "number": telefono,
        "mediatype": "document",
        "media": pdf_url,
        "caption": caption
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)

        if response.status_code in (200, 201):
            return {"enviado": True}
        else:
            return {
                "enviado": False,
                "error": f"HTTP {response.status_code}: {response.text}"
            }
    except requests.RequestException as e:
        return {
            "enviado": False,
            "error": f"Error de conexión: {str(e)}"
        }
