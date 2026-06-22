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
