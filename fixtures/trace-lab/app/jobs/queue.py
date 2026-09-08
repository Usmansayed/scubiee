"""Job queue. enqueue/dequeue are generic."""

_PENDING: list[dict] = []


def enqueue(job: dict) -> None:
    _PENDING.append(job)


def dequeue() -> dict:
    return _PENDING.pop(0) if _PENDING else {}
