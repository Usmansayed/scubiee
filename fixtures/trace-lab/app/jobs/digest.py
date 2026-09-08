"""Concrete job body — also touches telemetry side effects."""

from app.analytics.tracker import track
from app.utils.logger import log


def send_digest(job: dict) -> dict:
    log("digest")
    track("digest")
    return {"sent": job.get("to")}
