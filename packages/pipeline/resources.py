"""Resource Manager — adaptive scheduler for indexing / embedding.

Standalone subsystem (not MCP-specific). Every heavy indexing job should
call ``get_resource_manager().wait_for_capacity(...)`` or use ``throttle``.

Pressure levels:
  idle     → slight batch boost
  normal   → run at the calibrated batch (default)
  critical → only when free RAM is near-OOM; everything else keeps working
"""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterator, Literal, TypeVar

from pipeline.fair_schedule import EmbedPriority, get_embed_scheduler
from pipeline.resource_envelope import EnvelopeConfig, derive_envelope

Pressure = Literal["idle", "normal", "busy", "critical"]
JobKind = Literal["embed", "index", "sync", "graph", "generic"]

T = TypeVar("T")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def resources_disabled() -> bool:
    return os.environ.get("CTX_RM_DISABLE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass
class SystemSample:
    cpu_percent: float | None = None
    ram_percent: float | None = None
    ram_available_mb: float | None = None
    ram_total_mb: float | None = None
    ts: float = field(default_factory=time.time)
    source: str = "none"  # psutil | fallback | disabled

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdaptiveBudget:
    pressure: Pressure
    allow: bool
    batch_size: int
    workers: int
    pause_s: float
    reason: str = ""
    sample: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResourceManager:
    """Process-wide adaptive resource gate."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.embed_scheduler = get_embed_scheduler()
        self._last_sample: SystemSample | None = None
        self._last_pressure: Pressure = "normal"
        self._base_batch = self._resolve_base_batch()
        self._cpu_count = os.cpu_count() or 4
        self._base_workers = max(1, min(4, self._cpu_count // 2))
        self._envelope = derive_envelope(16_000, 6_000, self._base_batch, self._cpu_count)
        self._pending_envelope_tier: str | None = None
        self._pending_envelope_samples = 0
        self._last_envelope_sample: SystemSample | None = None
        self._prefs_enabled = True
        # thresholds (overridable)
        self.max_cpu_busy = _env_float("CTX_RM_MAX_CPU", 70.0)
        self.max_cpu_critical = _env_float("CTX_RM_CRITICAL_CPU", 90.0)
        self.min_free_ram_mb = _env_float("CTX_RM_MIN_FREE_RAM_MB", 256.0)
        self.max_ram_percent = _env_float("CTX_RM_MAX_RAM_PCT", 99.5)
        self.poll_s = max(0.05, _env_float("CTX_RM_POLL_MS", 250.0) / 1000.0)
        self._load_prefs()

    def _load_prefs(self) -> None:
        try:
            from pipeline.settings import load_prefs

            rm = load_prefs().get("resource_management") or {}
            if isinstance(rm, dict):
                if "enabled" in rm:
                    self._prefs_enabled = bool(rm["enabled"])
                if "max_cpu_busy" in rm:
                    self.max_cpu_busy = float(rm["max_cpu_busy"])
                if "max_cpu_critical" in rm:
                    self.max_cpu_critical = float(rm["max_cpu_critical"])
                if "min_free_ram_mb" in rm:
                    self.min_free_ram_mb = float(rm["min_free_ram_mb"])
        except Exception:  # noqa: BLE001
            pass

    def reload_prefs(self) -> None:
        """Re-read prefs.json (e.g. after dashboard settings POST)."""
        with self._lock:
            self._load_prefs()

    def is_disabled(self) -> bool:
        return resources_disabled() or not self._prefs_enabled

    def _resolve_base_batch(self) -> int:
        calibrated_batch = 16
        try:
            from pipeline.accel import load_accel

            prof = load_accel()
            if prof is not None:
                saved_winner = (prof.batch_calibration or {}).get("winner")
                calibrated_batch = max(1, int(saved_winner or prof.batch_size or calibrated_batch))
        except Exception:  # noqa: BLE001
            pass
        if "CTX_EMBED_BATCH" in os.environ:
            try:
                return min(calibrated_batch, max(1, int(os.environ["CTX_EMBED_BATCH"])))
            except ValueError:
                pass
        return calibrated_batch

    def refresh_base_from_accel(self) -> None:
        with self._lock:
            self._base_batch = self._resolve_base_batch()

    def _update_envelope(self, sample: SystemSample) -> EnvelopeConfig:
        if sample.ram_total_mb is None or sample.ram_available_mb is None:
            return self._envelope

        candidate = derive_envelope(
            sample.ram_total_mb,
            sample.ram_available_mb,
            self._base_batch,
            self._cpu_count,
        )
        with self._lock:
            if sample is self._last_envelope_sample:
                return self._envelope
            self._last_envelope_sample = sample
            if candidate.tier == self._envelope.tier:
                self._envelope = candidate
                self._pending_envelope_tier = None
                self._pending_envelope_samples = 0
                return self._envelope
            if candidate.tier == self._pending_envelope_tier:
                self._pending_envelope_samples += 1
            else:
                self._pending_envelope_tier = candidate.tier
                self._pending_envelope_samples = 1
            if self._pending_envelope_samples >= 2:
                self._envelope = candidate
                self._pending_envelope_tier = None
                self._pending_envelope_samples = 0
            return self._envelope

    def sample(self, *, force: bool = False) -> SystemSample:
        """Sample CPU/RAM. Cached briefly to avoid hammering the OS."""
        with self._lock:
            if (
                not force
                and self._last_sample
                and (time.time() - self._last_sample.ts) < self.poll_s
            ):
                return self._last_sample

        if self.is_disabled():
            s = SystemSample(source="disabled", cpu_percent=0.0, ram_percent=0.0)
            with self._lock:
                self._last_sample = s
            return s

        s = SystemSample()
        try:
            import psutil  # type: ignore

            # non-blocking first call may return 0.0 — use interval=None after warm
            cpu = psutil.cpu_percent(interval=0.05)
            vm = psutil.virtual_memory()
            s.cpu_percent = float(cpu)
            s.ram_percent = float(vm.percent)
            s.ram_available_mb = float(vm.available) / (1024 * 1024)
            s.ram_total_mb = float(vm.total) / (1024 * 1024)
            s.source = "psutil"
        except Exception:  # noqa: BLE001
            # Conservative fallback: assume normal load, unknown RAM
            s.cpu_percent = None
            s.ram_percent = None
            s.source = "fallback"
            try:
                from pipeline.hardware import load_hardware

                hw = load_hardware()
                if hw.get("ram_available_bytes"):
                    s.ram_available_mb = float(hw["ram_available_bytes"]) / (1024 * 1024)
                if hw.get("ram_total_bytes"):
                    s.ram_total_mb = float(hw["ram_total_bytes"]) / (1024 * 1024)
            except Exception:  # noqa: BLE001
                pass

        with self._lock:
            self._last_sample = s
        return s

    def classify(self, sample: SystemSample | None = None) -> Pressure:
        if self.is_disabled():
            return "idle"
        sample = sample or self.sample()
        # Only a real near-OOM stop. CPU spikes and Windows "RAM % used"
        # (file cache) must not freeze indexing.
        if (
            sample.ram_available_mb is not None
            and sample.ram_available_mb < self.min_free_ram_mb
        ):
            return "critical"
        cpu = sample.cpu_percent
        if cpu is None:
            return "normal"
        if cpu < 25.0:
            return "idle"
        return "normal"

    def budget(self, job: JobKind = "generic") -> AdaptiveBudget:
        sample = self.sample()
        pressure = self.classify(sample)
        envelope = self._update_envelope(sample)
        with self._lock:
            self._last_pressure = pressure
            base = self._base_batch
            workers = self._base_workers

        heavy = job in {"index", "graph"}

        if pressure == "critical":
            batch = 1
            pause = 0.5
            allow = False
            workers = 1
            reason = "almost no free RAM — pause to avoid OOM"
        elif pressure == "idle":
            if job == "embed":
                boost_cap = 32 if base <= 16 else 64
                batch = max(base, min(base * 2, boost_cap))
            else:
                batch = min(base * 2, 64 if not heavy else 32)
            pause = 0.0
            allow = True
            workers = min(workers + 1, 4)
            reason = "system idle — boost throughput"
        else:
            batch = base
            pause = 0.0
            allow = True
            reason = "run at calibrated budget"

        worker_ceiling = envelope.embed_workers if job == "embed" else envelope.index_workers
        return AdaptiveBudget(
            pressure=pressure,
            allow=allow,
            batch_size=max(1, min(int(batch), base, envelope.batch_ceiling)),
            workers=max(1, min(int(workers), worker_ceiling)),
            pause_s=float(pause),
            reason=reason,
            sample=sample.to_dict(),
        )

    def wait_for_capacity(
        self,
        job: JobKind = "generic",
        *,
        timeout_s: float = 120.0,
        on_wait: Callable[[AdaptiveBudget], None] | None = None,
    ) -> AdaptiveBudget:
        """Block until budget.allow or timeout. Always returns a budget."""
        deadline = time.time() + max(0.0, timeout_s)
        last: AdaptiveBudget | None = None
        while True:
            last = self.budget(job)
            if last.allow or self.is_disabled():
                if self.is_disabled():
                    last = AdaptiveBudget(
                        pressure="idle",
                        allow=True,
                        batch_size=self._base_batch,
                        workers=self._base_workers,
                        pause_s=0.0,
                        reason="RM disabled (env or prefs)",
                        sample=last.sample,
                    )
                return last
            if on_wait:
                try:
                    on_wait(last)
                except Exception:  # noqa: BLE001
                    pass
            if time.time() >= deadline:
                # Timed out: return last (allow may be False) — caller decides
                last.reason = f"{last.reason} (wait timeout)"
                return last
            time.sleep(min(2.0, max(0.2, last.pause_s or 0.5)))

    def apply_pause(self, budget: AdaptiveBudget) -> None:
        if budget.pause_s > 0 and not self.is_disabled():
            time.sleep(budget.pause_s)

    @contextmanager
    def throttle(self, job: JobKind = "generic") -> Iterator[AdaptiveBudget]:
        """Gate a work section; yields budget (may have allow=False after timeout)."""
        b = self.wait_for_capacity(job)
        try:
            yield b
        finally:
            self.apply_pause(b)

    def run_job(
        self,
        job: JobKind,
        fn: Callable[[], T],
        *,
        timeout_s: float = 120.0,
        project_id: str | None = None,
        priority: EmbedPriority = "recent",
    ) -> T | None:
        """Run fn if capacity allows, serializing expensive embeds fairly."""
        b = self.wait_for_capacity(job, timeout_s=timeout_s)
        if not b.allow:
            print(
                f"[resources] skip {job}: {b.reason} pressure={b.pressure}",
                file=sys.stderr,
                flush=True,
            )
            return None
        if job != "embed":
            try:
                return fn()
            finally:
                self.apply_pause(b)

        # Capacity/debounce waits happen before this section: only model work
        # occupies the process-wide single-flight scheduler.
        with self.embed_scheduler.hold(project_id or "default", priority, timeout_s) as acquired:
            if not acquired:
                return None
            try:
                return fn()
            finally:
                self.apply_pause(b)

    def status(self) -> dict[str, Any]:
        sample = self.sample(force=True)
        pressure = self.classify(sample)
        budgets = {j: self.budget(j).to_dict() for j in ("embed", "index", "sync", "graph")}
        # Drop unused workers field from public status budgets
        for b in budgets.values():
            b.pop("workers", None)
        return {
            "disabled": self.is_disabled(),
            "prefs_enabled": self._prefs_enabled,
            "pressure": pressure,
            "sample": sample.to_dict(),
            "base_batch": self._base_batch,
            "envelope": asdict(self._envelope),
            "thresholds": {
                "max_cpu_busy": self.max_cpu_busy,
                "max_cpu_critical": self.max_cpu_critical,
                "min_free_ram_mb": self.min_free_ram_mb,
                "max_ram_percent": self.max_ram_percent,
            },
            "budgets": budgets,
            "embed_scheduler": self.embed_scheduler.status(),
        }


_RM: ResourceManager | None = None
_RM_LOCK = threading.Lock()


def get_resource_manager() -> ResourceManager:
    global _RM
    with _RM_LOCK:
        if _RM is None:
            _RM = ResourceManager()
        return _RM


def reset_resource_manager_for_tests() -> None:
    global _RM
    with _RM_LOCK:
        _RM = None
