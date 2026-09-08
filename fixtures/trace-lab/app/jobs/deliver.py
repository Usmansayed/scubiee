"""Digest job also notifies — wires jobs to notify without auth vocab."""

from app.jobs.digest import send_digest
from app.notify.mailer import send


def deliver(job: dict) -> dict:
    result = send_digest(job)
    send(str(job.get("to") or ""), "digest")
    return result
