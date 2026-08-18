"""Fair, process-wide single-flight admission for expensive embedding work."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Literal

EmbedPriority = Literal["active", "recent", "idle"]
_PRIORITY = {"active": 0, "recent": 1, "idle": 2}


@dataclass
class _Waiter:
    project_id: str
    priority: EmbedPriority
    queued_at: float
    ticket: int


class FairEmbedScheduler:
    """Choose one embedder holder with priority, FIFO fairness, and aging."""

    def __init__(self, *, aging_s: float = 30.0) -> None:
        self.aging_s = max(0.001, aging_s)
        self._condition = threading.Condition(threading.RLock())
        self._holder: str | None = None
        self._waiters: list[_Waiter] = []
        self._next_ticket = 0

    def _effective_priority(self, waiter: _Waiter, now: float) -> int:
        age_steps = int((now - waiter.queued_at) / self.aging_s)
        return max(0, _PRIORITY[waiter.priority] - age_steps)

    def _next_waiter(self) -> _Waiter | None:
        if not self._waiters:
            return None
        now = time.monotonic()
        return min(
            self._waiters,
            key=lambda waiter: (self._effective_priority(waiter, now), waiter.ticket),
        )

    def acquire(self, project_id: str, priority: EmbedPriority = "recent", timeout_s: float = 120.0) -> bool:
        """Acquire the process-wide embed slot before ``timeout_s`` expires."""
        if priority not in _PRIORITY:
            raise ValueError(f"unknown embed priority: {priority}")
        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._condition:
            waiter = _Waiter(project_id, priority, time.monotonic(), self._next_ticket)
            self._next_ticket += 1
            self._waiters.append(waiter)
            while True:
                if self._holder is None and self._next_waiter() is waiter:
                    self._waiters.remove(waiter)
                    self._holder = project_id
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._waiters.remove(waiter)
                    self._condition.notify_all()
                    return False
                self._condition.wait(timeout=min(remaining, self.aging_s))

    def release(self, project_id: str) -> None:
        """Release a slot held by ``project_id``."""
        with self._condition:
            if self._holder != project_id:
                raise RuntimeError(f"{project_id} does not hold the embed scheduler")
            self._holder = None
            self._condition.notify_all()

    @contextmanager
    def hold(
        self, project_id: str, priority: EmbedPriority = "recent", timeout_s: float = 120.0
    ) -> Iterator[bool]:
        acquired = self.acquire(project_id, priority, timeout_s)
        try:
            yield acquired
        finally:
            if acquired:
                self.release(project_id)

    def status(self) -> dict[str, object]:
        with self._condition:
            return {
                "holder": self._holder,
                "queued": len(self._waiters),
                "queue": [
                    {
                        "project_id": waiter.project_id,
                        "priority": waiter.priority,
                        "age_s": round(time.monotonic() - waiter.queued_at, 3),
                    }
                    for waiter in sorted(self._waiters, key=lambda waiter: waiter.ticket)
                ],
            }


_SCHEDULER: FairEmbedScheduler | None = None
_SCHEDULER_LOCK = threading.Lock()


def get_embed_scheduler() -> FairEmbedScheduler:
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        if _SCHEDULER is None:
            _SCHEDULER = FairEmbedScheduler()
        return _SCHEDULER


def reset_embed_scheduler_for_tests() -> None:
    global _SCHEDULER
    with _SCHEDULER_LOCK:
        _SCHEDULER = None
