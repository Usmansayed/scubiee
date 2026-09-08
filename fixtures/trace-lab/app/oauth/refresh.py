"""Refresh entry — rotates then verifies claims."""

from app.oauth.rotate import rotate
from app.services.jwt_service import JwtService
from app.utils.logger import log


def refresh(token: str) -> dict:
    rotated = rotate(token)
    claims = JwtService().verify(rotated)
    log("refreshed")
    return claims
