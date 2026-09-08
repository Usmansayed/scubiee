"""Route parsed webhook to a handler."""

from app.webhooks.handlers import on_payment, on_refund


def route(event: dict) -> dict:
    kind = event.get("type") or ""
    if kind == "refund":
        return on_refund(event)
    return on_payment(event)
