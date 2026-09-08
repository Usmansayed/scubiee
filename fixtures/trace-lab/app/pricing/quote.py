"""Price quoting."""

from app.pricing.catalog import unit_price
from app.tax.compute import compute


def quote(cart: dict) -> dict:
    sub = 0
    for item in cart.get("items") or []:
        sub += unit_price(item["sku"]) * int(item.get("qty") or 1)
    tax = compute(sub, cart.get("region") or "US")
    return {"sub": sub, "tax": tax, "total": sub + tax}
