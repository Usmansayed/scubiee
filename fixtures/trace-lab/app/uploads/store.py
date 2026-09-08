"""Persist upload bytes."""

from app.cache.memo import put


def store(blob: bytes, user: str) -> str:
    key = "up:" + user
    put(key, {"n": len(blob)})
    return key
