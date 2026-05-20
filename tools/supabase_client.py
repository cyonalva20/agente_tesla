import os
from datetime import datetime, timezone
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

_supabase_client: Client | None = None

# ✅ Valores canónicos que usa ciclos_academicos
GRADOS_VALIDOS = {
    "cepu",
    "5to_secundaria",
    "4to_secundaria",
    "repaso",
    "pre_universitario"
}

# ✅ Alias para normalizar lo que viene de alumnos u otros orígenes
GRADOS_ALIAS = {
    "5to secundaria":      "5to_secundaria",
    "5to de secundaria":   "5to_secundaria",
    "4to secundaria":      "4to_secundaria",
    "4to de secundaria":   "4to_secundaria",
    "pre universitario":   "pre_universitario",
    "preuniversitario":    "pre_universitario",
}


def normalizar_grado(grado: str) -> str:
    """
    Normaliza el valor de grado al formato canónico de ciclos_academicos.
    Lanza ValueError si no se reconoce.
    """
    normalizado = grado.strip().lower().replace(" ", "_")
    if normalizado in GRADOS_VALIDOS:
        return normalizado
    alias = GRADOS_ALIAS.get(grado.strip().lower())
    if alias:
        return alias
    raise ValueError(
        f"Grado no reconocido: '{grado}'. "
        f"Valores válidos: {sorted(GRADOS_VALIDOS)}"
    )


def _get_client() -> Client:
    """Lazy initialization del cliente Supabase."""
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError(
                "SUPABASE_URL y SUPABASE_KEY deben estar configurados en .env"
            )
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase_client


def consultar_ciclos(grado: str) -> list:
    """
    Consulta ciclos académicos disponibles para un grado específico.
    GET ciclos_academicos WHERE grado=grado AND vacantes_disponibles > 0
    """
    grado_normalizado = normalizar_grado(grado)
    response = (
        _get_client().table("ciclos_academicos")
        .select("*")
        .eq("grado", grado_normalizado)
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
    # ✅ Normalizar grado antes de persistir para mantener consistencia
    if "grado" in datos:
        datos["grado"] = normalizar_grado(datos["grado"])

    response = (
        _get_client().table("alumnos")
        .upsert(datos, on_conflict="dni_alumno")
        .execute()
    )
    return response.data[0] if response.data else {}


def actualizar_estado_alumno(
    alumno_id: str,
    nuevo_estado: str,
    metadata: dict = None,       # ✅ Fix: default mutable corregido
    session_id: str = None       # ✅ Nuevo: session_id persistido
) -> dict:
    """
    Actualiza el estado de un alumno y registra el cambio en historial_estados.
    1. Obtiene el estado anterior del alumno.
    2. UPDATE alumnos SET estado=nuevo_estado WHERE id=alumno_id.
    3. INSERT en historial_estados con estado_anterior, estado_nuevo,
       metadata, session_id y timestamp=now().
    Retorna el registro actualizado.
    """
    metadata = metadata or {}   # ✅ Fix: evita default mutable compartido

    # 1. Obtener estado anterior
    alumno_actual = (
        _get_client().table("alumnos")
        .select("estado")
        .eq("id", alumno_id)
        .limit(1)
        .execute()
    )
    estado_anterior = (
        alumno_actual.data[0]["estado"] if alumno_actual.data else None
    )

    # 2. Actualizar estado del alumno
    response = (
        _get_client().table("alumnos")
        .update({"estado": nuevo_estado})
        .eq("id", alumno_id)
        .execute()
    )

    # 3. Registrar en historial_estados
    historial_response = (
        _get_client().table("historial_estados").insert({
            "alumno_id":      alumno_id,
            "estado_anterior": estado_anterior,
            "estado_nuevo":    nuevo_estado,
            "metadata":        metadata,
            "session_id":      session_id,   # ✅ Nuevo: persiste el session_id
            "timestamp":       datetime.now(timezone.utc).isoformat()
        }).execute()
    )

    # ✅ Nuevo: error explícito si el historial no se guardó
    if not historial_response.data:
        raise RuntimeError(
            f"Error al registrar historial para alumno {alumno_id}"
        )

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