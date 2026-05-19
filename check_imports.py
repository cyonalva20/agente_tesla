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
    from tools.supabase_client import consultar_ciclos, upsert_alumno, actualizar_estado_alumno, obtener_alumno_por_dni, obtener_alumno_por_id, consultar_ciclo_por_codigo
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
    print("OK pdf_generator.py")
except Exception as e:
    print(f"FAIL pdf_generator.py: {e}")

try:
    from main import app
    print("OK main.py")
except Exception as e:
    print(f"FAIL main.py: {e}")

print("\nVerificacion completa.")
