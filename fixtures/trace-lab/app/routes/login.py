"""HTTP login route — caller of authenticate."""

from app.middleware.auth import authenticate


def login(request: dict) -> dict:
    return authenticate(request)
