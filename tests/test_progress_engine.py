"""Shared progress engine: monotonic, measured, never a frozen fake percent."""

from __future__ import annotations

import io
import time
from pathlib import Path

import numpy as np
import pytest

from pipeline.progress import ProgressModel, ProgressRenderer, Stage


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class _TTY(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


def _plan() -> list[Stage]:
    return [Stage("a", "Alpha", 1), Stage("b", "Beta", 3), Stage("c", "Gamma", 1)]


def test_weighted_fraction_reflects_measured_work() -> None:
    m = ProgressModel(_plan())
    m.begin("b", total=100)
    m.update(50)
    snap = m.snapshot()
    assert snap.fraction == pytest.approx(0.2 + 0.6 * 0.5)
    assert snap.percent == 50
    assert snap.step == 2 and snap.steps == 3


def test_fraction_never_moves_backward() -> None:
    m = ProgressModel(_plan())
    m.begin("b", total=100)
    m.update(80)
    high = m.snapshot().fraction
    m.update(10)
    m.begin("a")
    m.update(5, 1000)
    assert m.snapshot().fraction >= high
    m.milestone(0.0, "anything")
    assert m.snapshot().fraction >= high


def test_never_100_until_complete() -> None:
    m = ProgressModel(_plan())
    m.begin("c", total=10)
    m.update(10)
    snap = m.snapshot()
    assert snap.percent == 99
    assert not snap.done
    m.complete()
    snap = m.snapshot()
    assert snap.percent == 100 and snap.fraction == 1.0 and snap.done


def test_indeterminate_stage_hides_percent() -> None:
    m = ProgressModel(_plan())
    m.begin("b")
    snap = m.snapshot()
    assert snap.percent is None
    assert not snap.measurable
    assert snap.fraction == pytest.approx(0.2)


def test_legacy_milestones_are_monotonic_floors() -> None:
    m = ProgressModel()
    m.milestone(0.30, "Installing")
    m.milestone(0.10, "Something earlier")
    assert m.snapshot().fraction == pytest.approx(0.30)
    for _ in range(50):
        m.milestone(m.snapshot().fraction, "Installing packages", until=0.5)
    assert m.snapshot().fraction == pytest.approx(0.30)
    assert m.snapshot().percent is None


def test_eta_from_measured_rate() -> None:
    clock = _Clock()
    m = ProgressModel(_plan(), clock=clock)
    m.begin("b", total=100)
    clock.t = 10.0
    m.update(25)
    eta = m.snapshot().eta_s
    assert eta == pytest.approx(30.0)


def test_unknown_stage_key_only_relabels() -> None:
    m = ProgressModel(_plan())
    m.begin("a")
    m.begin("sync", label="Checking for changes")
    snap = m.snapshot()
    assert snap.label == "Checking for changes"
    assert snap.step == 1


def test_renderer_indeterminate_line_has_spinner_and_clock_not_percent() -> None:
    clock = _Clock()
    m = ProgressModel(_plan(), clock=clock)
    buf = _TTY()
    r = ProgressRenderer(m, buf, color=False)
    m.begin("b")
    clock.t = 75.0
    plain, _ = r.compose(m.snapshot(), spinner="⠋")
    assert "⠋" in plain
    assert "%" not in plain
    assert "Beta" in plain
    assert "step 2/3" in plain
    assert "1m15s" in plain


def test_renderer_measurable_line_shows_percent_count_and_eta() -> None:
    clock = _Clock()
    m = ProgressModel(_plan(), clock=clock)
    r = ProgressRenderer(m, _TTY(), color=False)
    m.begin("b", total=3000)
    clock.t = 10.0
    m.update(1500)
    plain, _ = r.compose(m.snapshot(), spinner="⠋")
    assert "50%" in plain
    assert "1,500/3,000" in plain
    assert "left" in plain


def test_ticker_animates_while_producer_is_silent() -> None:
    m = ProgressModel(_plan())
    buf = _TTY()
    r = ProgressRenderer(m, buf, color=False, interval=0.02)
    m.begin("b")
    r.activate()
    time.sleep(0.3)
    r.stop()
    frames = {chunk.strip()[:1] for chunk in buf.getvalue().split("\r") if chunk.strip()}
    assert len(frames) >= 3


def test_non_tty_logs_are_sparse() -> None:
    m = ProgressModel(_plan())
    buf = io.StringIO()
    r = ProgressRenderer(m, buf, tty=False, color=False)
    r.activate()
    m.begin("b", total=10_000)
    for i in range(10_000):
        m.update(i)
        r.refresh()
    m.complete()
    r.refresh()
    lines = buf.getvalue().splitlines()
    assert 3 <= len(lines) <= 15


def test_init_progress_full_run_is_monotonic_without_big_jumps() -> None:
    from pipeline.cli_ui import InitProgress

    from pipeline.cli_ui import INIT_STAGES

    buf = _TTY()
    bar = InitProgress(stream=buf)
    seen: list[float] = []
    measured_steps: list[float] = []
    total_w = sum(s.weight for s in INIT_STAGES)
    max_indeterminate = max(s.weight for s in INIT_STAGES if s.key not in {"parse", "chunk", "embed"}) / total_w

    def record(measured: bool = False) -> None:
        f = bar.snapshot().fraction
        if measured and seen:
            measured_steps.append(f - seen[-1])
        seen.append(f)

    bar.stage("prepare"); record()
    bar.stage("scan"); record()
    bar.stage("parse", total=400); record()
    for i in range(0, 401, 4):
        bar.update(i, 400); record(True)
    bar.stage("link"); record()
    bar.stage("chunk", total=1000); record()
    for i in range(0, 1001, 250):
        bar.update(i, 1000); record(True)
    bar.stage("embed", total=2000); record()
    for i in range(0, 2001, 16):
        bar.update(i, 2000); record(True)
    bar.stage("write"); record()
    bar.stage("engine"); record()
    assert all(b >= a for a, b in zip(seen, seen[1:]))
    assert max(measured_steps) <= 0.01
    assert max(b - a for a, b in zip(seen, seen[1:])) <= max_indeterminate + 1e-9
    assert seen[-1] < 1.0
    bar.done(10)
    assert bar.snapshot().percent == 100


def test_extract_reports_per_file_progress(tmp_path: Path) -> None:
    from graphify.extract import extract

    files = []
    for i in range(5):
        p = tmp_path / f"m{i}.py"
        p.write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
        files.append(p)
    calls: list[tuple[int, int]] = []
    extract(files, root=tmp_path, cache_root=tmp_path, parallel=False, progress=lambda d, t: calls.append((d, t)))
    assert calls[0][1] == 5
    assert calls[-1] == (5, 5)
    assert all(b[0] >= a[0] for a, b in zip(calls, calls[1:]))


def test_embed_progress_counts_cached_chunks(monkeypatch, cpu_accel_profile) -> None:
    del cpu_accel_profile
    from pipeline.embedder import Embedder, text_key

    embedder = Embedder(model="nomic-ai/CodeRankEmbed", batch_size=2, quiet=True)
    embedder.backend = "fastembed"
    embedder.device = "cpu"
    texts = ["a", "b", "c", "d", "e", "f"]
    embedder.cache = {text_key("d:" + t): [1.0, 1.0, 1.0, 1.0] for t in texts[:4]}
    monkeypatch.setattr(embedder, "_encode_batch", lambda batch: np.ones((len(batch), 4), dtype=np.float32))
    monkeypatch.setattr(
        "pipeline.resources.get_resource_manager",
        lambda: (_ for _ in ()).throw(ImportError()),
    )
    calls: list[tuple[int, int]] = []
    embedder.embed_many(texts, progress=lambda d, t: calls.append((d, t)))
    assert calls[0] == (4, 6)
    assert calls[-1] == (6, 6)
