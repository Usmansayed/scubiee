"""Side-channel event fan-out. Called from authenticate but not required
to understand the authentication execution path."""

from app.http.client import get


def track(event: str) -> None:
    get("/events", {"e": event})
