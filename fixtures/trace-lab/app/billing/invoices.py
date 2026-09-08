"""Payment charges.

Customer authentication tokens for the payment API are unrelated to
product login. This file is a lexical distractor for queries containing
the word authentication.
"""

from app.audit.record import record
from app.http.client import get


def charge(user_id: str, cents: int) -> bool:
    payload = get("/pay", {"user": user_id, "cents": cents})
    record("charge", user_id)
    return bool(payload)
