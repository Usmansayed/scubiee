"""HTTP authentication middleware.

Public entry is authenticate(). Downstream helpers use generic names
(verify / decode / resolve) so lexical search for "authentication" cannot
recover the execution path by vocabulary alone.
"""

from app.analytics.tracker import track
from app.services.jwt_service import JwtService
from app.utils.logger import log


def authenticate(request: dict) -> dict:
    token = extract_bearer(request)
    payload = JwtService().verify(token)
    log("ok")
    track("login")
    return payload


def extract_bearer(request: dict) -> str:
    header = request.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header.split(" ", 1)[1]
    raise ValueError("missing token")
