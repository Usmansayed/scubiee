"""Wires the welcome handler into the event table."""

from app.events.registry import bind
from app.handlers.welcome import handle


def start() -> None:
    bind("welcome", handle)
