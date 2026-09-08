"""Reserve stock for a checkout."""

from app.inventory.stock import available
from app.inventory.warehouse import levels


def reserve(sku: str, qty: int) -> bool:
    if not available(sku, qty):
        return False
    _ = levels(sku)
    return True
