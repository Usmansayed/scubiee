"""Liveness probe. Unrelated to authentication."""


def health() -> dict:
    return {"ok": True}
