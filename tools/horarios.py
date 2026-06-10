from tools.supabase_client import _get_client

def obtener_url_horario(ciclo_codigo: str) -> str | None:
    """
    Construye la URL pública para el horario de un ciclo determinado.
    Se asume que los horarios están en el bucket 'documents' bajo la ruta 'horarios/CODIGO.pdf'.
    """
    try:
        client = _get_client()
        file_path = f"horarios/{ciclo_codigo}.pdf"
        
        # Obtener URL pública (esto no valida si el archivo existe o no, 
        # solo construye la URL basándose en la configuración del bucket)
        url_publica = client.storage.from_("documents").get_public_url(file_path)
        
        return url_publica
    except Exception as e:
        print(f"[obtener_url_horario] Error: {e}")
        return None
