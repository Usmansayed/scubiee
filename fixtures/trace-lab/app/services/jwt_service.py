"""Claim checking. Downstream of the middleware entry."""

from app.config.security import TOKEN_TTL
from app.repositories.user_repo import UserRepository
from app.utils.logger import log
from app.utils.token import decode


class JwtService:
    def verify(self, value: str) -> dict:
        claims = decode(value)
        age = int(claims.get("age", 0))
        if age > TOKEN_TTL:
            raise ValueError("expired")
        UserRepository().resolve(claims["sub"])
        log("verified")
        return claims
