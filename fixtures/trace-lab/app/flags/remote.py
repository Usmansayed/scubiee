"""Remote flag config fetch."""

from app.http.client import get


def fetch(flag: str) -> dict:
    return get("/flags", {"flag": flag})
