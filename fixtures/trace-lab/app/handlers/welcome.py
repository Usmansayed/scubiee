"""Welcome handler. The function is named handle, not on_user_event."""

from app.analytics.tracker import track
from app.services.session import start
from app.utils.logger import log


def handle(payload: dict) -> dict:
    log("welcome")
    track("welcome")
    start(str(payload.get("user") or ""))
    return {"user": payload.get("user")}
