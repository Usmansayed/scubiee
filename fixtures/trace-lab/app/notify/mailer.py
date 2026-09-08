"""Outbound notification. send is generic."""

from app.http.client import get


def send(to: str, body: str) -> dict:
    return get("/notify", {"to": to, "body": body})
