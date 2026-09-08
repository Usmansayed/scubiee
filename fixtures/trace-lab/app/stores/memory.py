"""In-memory store. Method name fetch is inherited and generic."""

from app.stores.base import Store


class MemoryStore(Store):
    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def fetch(self, key: str) -> dict:
        return self._rows.get(key) or {"id": key}
