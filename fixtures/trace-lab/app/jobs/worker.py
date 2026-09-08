"""Worker loop. run/execute are generic names."""

from app.jobs.queue import dequeue
from app.jobs.runner import execute


def run() -> dict:
    job = dequeue()
    return execute(job)
