import os
import stripe
from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


@tool
def verificar_pago(charge_id: str) -> dict:
    """
    Verifica el estado de un pago en Stripe.
    Intenta primero con PaymentIntent; si falla, intenta con Charge.
    Si status == "succeeded": retorna {"status": "paid", "amount": monto/100, "currency": ...}
    Si no: retorna {"status": charge.status, "amount": 0}
    """
    try:
        # Intentar como PaymentIntent primero (pi_...)
        if charge_id.startswith("pi_"):
            intent = stripe.PaymentIntent.retrieve(charge_id)
            if intent.status == "succeeded":
                return {
                    "status": "paid",
                    "amount": intent.amount / 100,
                    "currency": intent.currency
                }
            else:
                return {
                    "status": intent.status,
                    "amount": 0
                }
        else:
            # Intentar como Charge (ch_...)
            charge = stripe.Charge.retrieve(charge_id)
            if charge.status == "succeeded":
                return {
                    "status": "paid",
                    "amount": charge.amount / 100,
                    "currency": charge.currency
                }
            else:
                return {
                    "status": charge.status,
                    "amount": 0
                }
    except stripe.error.StripeError as e:
        return {
            "status": "error",
            "amount": 0,
            "error": str(e)
        }

@tool
def generar_link_pago(nombre_producto: str, monto_soles: int) -> str:
    """
    Genera un enlace de pago (Payment Link) en Stripe dinámicamente.
    nombre_producto: Nombre del ciclo (ej. "Ciclo Intensivo G-SEC5-2026-B")
    monto_soles: El precio del ciclo en soles (ej. 750).
    Retorna la URL del enlace de pago generado.
    """
    try:
        payment_link = stripe.PaymentLink.create(
            line_items=[
                {
                    "price_data": {
                        "currency": "pen",
                        "product_data": {"name": nombre_producto},
                        "unit_amount": monto_soles * 100,  # Stripe procesa en céntimos
                    },
                    "quantity": 1,
                },
            ],
        )
        return payment_link.url
    except Exception as e:
        return f"Error al generar enlace de pago: {str(e)}"

@tool
def verificar_pago_por_email(email: str) -> dict:
    """
    Verifica si existe un pago completado en Stripe asociado al correo electrónico.
    Busca en las últimas 50 sesiones de Checkout.
    Si status == "paid": retorna {"status": "paid", "amount": monto/100, "currency": ...}
    Si no: retorna {"status": "not_found", "amount": 0}
    """
    try:
        sessions = stripe.checkout.Session.list(limit=50)
        email_lower = email.strip().lower()
        for s in sessions.data:
            s_email = s.customer_details.email if s.customer_details else ""
            if s_email and s_email.strip().lower() == email_lower:
                if s.payment_status == "paid":
                    return {
                        "status": "paid",
                        "amount": s.amount_total / 100 if s.amount_total else 0,
                        "currency": s.currency
                    }
        
        return {
            "status": "not_found",
            "amount": 0
        }
    except stripe.error.StripeError as e:
        return {
            "status": "error",
            "amount": 0,
            "error": str(e)
        }
