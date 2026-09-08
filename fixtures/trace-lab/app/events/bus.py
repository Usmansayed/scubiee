"""In-process event bus. emit/lookup have no auth vocabulary."""

from app.events.registry import lookup


def emit(name: str, payload: dict) -> dict:
    fn = lookup(name)
    return fn(payload)
