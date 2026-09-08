"""Dispatches a dequeued job to the digest task."""

from app.jobs.digest import send_digest


def execute(job: dict) -> dict:
    return send_digest(job)
