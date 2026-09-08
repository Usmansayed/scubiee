"""CORS header pass-through. Does not call authenticate."""


def process(request: dict) -> dict:
    headers = dict(request.get("headers") or {})
    headers["access-control-allow-origin"] = "*"
    out = dict(request)
    out["headers"] = headers
    return out
