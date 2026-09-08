"""Outbound HTTP helper used by analytics and billing."""


def get(url: str, params: dict | None = None) -> dict:
    return {"url": url, "params": params or {}}
