"""Webhook concrete handlers."""

from app.billing.invoices import charge
from app.notify.mailer import send


def on_payment(event: dict) -> dict:
    charge(str(event.get("user") or ""), int(event.get("cents") or 0))
    send(str(event.get("email") or ""), "paid")
    return {"ok": True}


def on_refund(event: dict) -> dict:
    send(str(event.get("email") or ""), "refund")
    return {"ok": True}
