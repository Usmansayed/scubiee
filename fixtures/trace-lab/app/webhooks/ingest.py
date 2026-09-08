"""Webhook ingest entry."""

from app.webhooks.parse import parse
from app.webhooks.route import route
from app.webhooks.verify_sig import verify_sig


def ingest(raw: bytes, headers: dict) -> dict:
    verify_sig(raw, headers.get("x-sig") or "")
    event = parse(raw)
    return route(event)
