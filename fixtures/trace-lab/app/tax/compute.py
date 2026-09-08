"""Tax computation."""

from app.tax.rates import rate_for


def compute(cents: int, region: str) -> int:
    return int(cents * rate_for(region))
