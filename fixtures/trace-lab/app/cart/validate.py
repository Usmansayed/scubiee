"""Cart validation before checkout."""

from app.inventory.stock import available


def validate(cart: dict) -> dict:
    for item in cart.get("items") or []:
        if not available(item["sku"], int(item.get("qty") or 1)):
            raise ValueError("oos")
    return cart
