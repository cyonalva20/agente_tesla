import os
import requests
from dotenv import load_dotenv

load_dotenv()

APIPERU_TOKEN = os.getenv("APIPERU_TOKEN")


def validar_dni(dni: str) -> dict:
    """
    Valida un DNI peruano contra la API de RENIEC.
    GET https://api.apis.net.pe/v2/reniec/dni?numero={dni}
    Header: Authorization: Bearer {APIPERU_TOKEN}
    Si responde 200: retorna {"valido": True, "nombres": ..., "apellidos": ...}
    Si falla: retorna {"valido": False, "error": "DNI no encontrado"}
    """
    url = f"https://api.apis.net.pe/v2/reniec/dni?numero={dni}"
    headers = {
        "Authorization": f"Bearer {APIPERU_TOKEN}"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            return {
                "valido": True,
                "nombres": data.get("nombres", ""),
                "apellidos": f"{data.get('apellidoPaterno', '')} {data.get('apellidoMaterno', '')}".strip()
            }
        else:
            return {
                "valido": False,
                "error": "DNI no encontrado"
            }
    except requests.RequestException as e:
        return {
            "valido": False,
            "error": f"Error de conexión: {str(e)}"
        }
