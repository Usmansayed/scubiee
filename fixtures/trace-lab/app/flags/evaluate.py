"""Feature flag evaluation."""

from app.flags.remote import fetch
from app.flags.rules import match


def evaluate(flag: str, user: str) -> bool:
    rules = fetch(flag)
    return match(rules, user)
