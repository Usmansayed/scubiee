"""Warehouse level lookup."""

from app.config.database import connect


def levels(sku: str) -> int:
    db = connect()
    return int(db.get(sku, 0)) if isinstance(db, dict) else 10
