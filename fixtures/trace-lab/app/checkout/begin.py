"""Checkout orchestration — many related hops."""

from app.billing.invoices import charge
from app.cart.validate import validate
from app.inventory.reserve import reserve
from app.pricing.quote import quote
from app.shipping.schedule import schedule
from app.utils.logger import log


def begin(cart: dict, user_id: str) -> dict:
    validate(cart)
    priced = quote(cart)
    for item in cart.get("items") or []:
        reserve(item["sku"], int(item.get("qty") or 1))
    ok = charge(user_id, int(priced["total"]))
    if not ok:
        raise ValueError("pay")
    ship = schedule(cart.get("id") or "o1", cart.get("email") or "a@b.c")
    log("checkout-ok")
    return {"priced": priced, "ship": ship}
