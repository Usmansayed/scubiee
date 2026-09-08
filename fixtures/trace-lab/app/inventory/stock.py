"""Inventory availability checks."""

from app.inventory.warehouse import levels


def available(sku: str, qty: int) -> bool:
    return levels(sku) >= qty
