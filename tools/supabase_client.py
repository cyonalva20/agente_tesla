import os
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

_supabase_client: Client | None = None


def _get_client() -> Client:
    """Lazy initialization del cliente Supabase."""
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("SUPABASE_URL y SUPABASE_KEY deben estar configurados en .env")
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def consultar_ciclos(grado: str) -> list:
    """
    Consulta ciclos académicos disponibles para un grado específico.
    GET ciclos_academicos WHERE grado=grado AND vacantes_disponibles > 0
    """
    response = (
        _get_client().table("ciclos_academicos")
        .select("*")
        .eq("grado", grado)
        .gt("vacantes_disponibles", 0)
        .execute()
    )
    return response.data


def upsert_alumno(datos: dict) -> dict:
    """
    Inserta o actualiza un alumno en la tabla alumnos.
    UPSERT con onConflict='dni_alumno'.
    Retorna el registro completo con id generado.
    """
    response = (
        _get_client().table("alumnos")
        .upsert(datos, on_conflict="dni_alumno")
        .execute()
    )
    return response.data[0] if response.data else {}


def actualizar_estado_alumno(alumno_id: str, nuevo_estado: str, metadata: dict = {}) -> dict:
    """
    Actualiza el estado de un alumno y registra el cambio en historial_estados.
    1. Obtiene el estado anterior del alumno.
    2. UPDATE alumnos SET estado=nuevo_estado WHERE id=alumno_id.
    3. INSERT en historial_estados con estado_anterior, estado_nuevo, metadata, timestamp=now().
    Retorna el registro actualizado.
    """
    # Obtener estado anterior
    alumno_actual = (
        _get_client().table("alumnos")
        .select("estado")
        .eq("id", alumno_id)
        .limit(1)
        .execute()
    )
    estado_anterior = alumno_actual.data[0]["estado"] if alumno_actual.data else None

    # Actualizar estado del alumno
    response = (
        _get_client().table("alumnos")
        .update({"estado": nuevo_estado})
        .eq("id", alumno_id)
        .execute()
    )

    # Registrar en historial_estados
    _get_client().table("historial_estados").insert({
        "alumno_id": alumno_id,
        "estado_anterior": estado_anterior,
        "estado_nuevo": nuevo_estado,
        "metadata": metadata,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }).execute()

    return response.data[0] if response.data else {}


def obtener_alumno_por_dni(dni: str) -> dict | None:
    """
    Busca un alumno por su DNI.
    SELECT * FROM alumnos WHERE dni_alumno=dni LIMIT 1.
    Retorna el registro o None si no existe.
    """
    response = (
        _get_client().table("alumnos")
        .select("*")
        .eq("dni_alumno", dni)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def obtener_alumno_por_id(alumno_id: str) -> dict | None:
    """
    Busca un alumno por su ID (UUID).
    SELECT * FROM alumnos WHERE id=alumno_id LIMIT 1.
    Retorna el registro o None si no existe.
    """
    response = (
        _get_client().table("alumnos")
        .select("*")
        .eq("id", alumno_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def consultar_ciclo_por_codigo(codigo: str) -> dict | None:
    """
    Busca un ciclo académico por su código.
    SELECT * FROM ciclos_academicos WHERE codigo=codigo LIMIT 1.
    Retorna el registro o None si no existe.
    """
    response = (
        _get_client().table("ciclos_academicos")
        .select("*")
        .eq("codigo", codigo)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None
