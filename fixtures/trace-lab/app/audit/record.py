"""Audit trail writer."""

from app.analytics.tracker import track
from app.config.database import connect
from app.utils.logger import log


def record(action: str, user: str) -> dict:
    log(action)
    track(action)
    db = connect()
    return {"action": action, "user": user, "db": db}
