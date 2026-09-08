"""Shipping schedule after payment."""

from app.http.client import get
from app.notify.mailer import send


def schedule(order_id: str, to: str) -> dict:
    eta = get("/ship", {"order": order_id})
    send(to, "shipped")
    return eta
