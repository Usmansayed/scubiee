"""Simple rate limit. allow is generic."""

_BUCKET: dict[str, int] = {}


def allow(key: str, limit: int = 10) -> bool:
    n = _BUCKET.get(key, 0) + 1
    _BUCKET[key] = n
    return n <= limit
