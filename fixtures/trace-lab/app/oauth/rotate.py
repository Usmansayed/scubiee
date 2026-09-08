"""Token rotation helper before verify."""

from app.oauth.nonce import stamp


def rotate(token: str) -> str:
    return stamp(token) + "|rot"
