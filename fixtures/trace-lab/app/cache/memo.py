"""Tiny in-process cache. get/put are generic names on purpose."""

_STORE: dict[str, object] = {}


def get(key: str):
    return _STORE.get(key)


def put(key: str, value: object) -> None:
    _STORE[key] = value
