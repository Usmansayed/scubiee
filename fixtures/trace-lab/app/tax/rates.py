"""Tax rates by region."""


def rate_for(region: str) -> float:
    return 0.08 if region == "US" else 0.2
