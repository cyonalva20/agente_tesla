import os
import requests
from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

APIPERU_TOKEN = os.getenv("APIPERU_TOKEN")

@tool
def validar_dni(dni: str) -> dict:
    # ✅ URL correcta
    url = f"https://api.decolecta.com/v1/reniec/dni?numero={dni}"
    headers = {"Authorization": f"Bearer {APIPERU_TOKEN}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            return {
                "valido": True,
                "fuente": "reniec",
                "nombres":   data.get("first_name", ""),
                "apellidos": (
                    f"{data.get('first_last_name', '')} "
                    f"{data.get('second_last_name', '')}"
                ).strip()
            }

        print(f"[RENIEC] DNI {dni} → HTTP {response.status_code} | {response.text[:200]}")

    except requests.RequestException as e:
        print(f"[RENIEC] DNI {dni} → Error de conexión: {e}")

    return _validar_dni_supabase(dni)

def _validar_dni_supabase(dni: str) -> dict:
    """
    Fallback: busca el DNI en la tabla alumnos de Supabase.
    Útil cuando RENIEC no está disponible o el token expiró.
    """
    try:
        from tools.supabase_client import obtener_alumno_por_dni
        alumno = obtener_alumno_por_dni(dni)

        if alumno:
            print(f"[RENIEC] DNI {dni} → encontrado en Supabase (fallback)")
            return {
                "valido": True,
                "fuente": "supabase",
                "nombres":   alumno.get("nombres", ""),
                "apellidos": alumno.get("apellidos", "")
            }
    except Exception as e:
        print(f"[RENIEC] Fallback Supabase falló para DNI {dni}: {e}")

    return {
        "valido": False,
        "error": "DNI no encontrado en RENIEC ni en base de datos"
    }
