import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("Verificando imports...")

try:
    from orchestrator import Orchestrator
    print("OK orchestrator.py")
except Exception as e:
    print(f"FAIL orchestrator.py: {e}")

try:
    from agents.sdr import run_sdr_agent
    from agents.administrativo import run_admin_agent
    from agents.financiero import run_financiero_agent
    print("OK agents/")
except Exception as e:
    print(f"FAIL agents/: {e}")

try:
    from tools.supabase_client import (
        consultar_ciclos,
        upsert_alumno,
        actualizar_estado_alumno,
        obtener_alumno_por_dni,
        obtener_alumno_por_id,
        consultar_ciclo_por_codigo,
    )
    print("OK supabase_client.py")
except Exception as e:
    print(f"FAIL supabase_client.py: {e}")

try:
    from tools.reniec import validar_dni
    print("OK reniec.py")
except Exception as e:
    print(f"FAIL reniec.py: {e}")

try:
    from tools.stripe_client import verificar_pago
    print("OK stripe_client.py")
except Exception as e:
    print(f"FAIL stripe_client.py: {e}")

try:
    from tools.pipedrive_client import registrar_lead
    print("OK pipedrive_client.py")
except Exception as e:
    print(f"FAIL pipedrive_client.py: {e}")

try:
    from tools.evolution_whatsapp import enviar_mensaje, enviar_documento
    print("OK evolution_whatsapp.py")
except Exception as e:
    print(f"FAIL evolution_whatsapp.py: {e}")

try:
    from tools.pdf_generator import generar_constancia
    import inspect

    # Verificar que la firma acepta (alumno: dict, ciclo: dict)
    sig = inspect.signature(generar_constancia)
    params = list(sig.parameters.keys())
    assert params == ["alumno", "ciclo"], (
        f"Firma inesperada en generar_constancia: {params}"
    )

    # Verificar que retorna dict con las claves esperadas
    # Se usa un mock mínimo para no tocar Supabase ni el filesystem real
    _ALUMNO_MOCK = {
        "id": "test-uuid-1234",
        "nombres": "Test",
        "apellidos": "Mock",
        "dni_alumno": "00000000",
        "grado": "5to",
        "fecha_matricula": "2026-01-01",
        "monto_pagado": 0,
        "charge_id": "ch_test",
    }
    _CICLO_MOCK = {
        "nombre": "Ciclo Mock",
        "codigo": "MOCK-001",
        "horario": "Lunes 8am",
        "modalidad": "Presencial",
        "precio_soles": 0,
        "fecha_inicio": "2026-01-01",
    }

    resultado = generar_constancia(_ALUMNO_MOCK, _CICLO_MOCK)

    assert isinstance(resultado, dict), (
        f"generar_constancia debe retornar dict, retornó {type(resultado)}"
    )
    for clave in ("archivo_local", "url_publica", "constancia_numero"):
        assert clave in resultado, (
            f"generar_constancia: falta la clave '{clave}' en el retorno"
        )

    print("OK pdf_generator.py")

except AssertionError as e:
    print(f"FAIL pdf_generator.py (contrato): {e}")
except Exception as e:
    print(f"FAIL pdf_generator.py: {e}")

try:
    from main import app
    print("OK main.py")
except Exception as e:
    print(f"FAIL main.py: {e}")

print("\nVerificacion completa.")