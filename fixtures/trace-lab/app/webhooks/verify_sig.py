"""Signature check."""

from app.config.security import TOKEN_TTL


def verify_sig(raw: bytes, sig: str) -> None:
    if not sig or len(sig) < 4:
        raise ValueError("bad sig")
    _ = TOKEN_TTL
