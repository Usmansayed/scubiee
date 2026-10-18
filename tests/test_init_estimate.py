"""Init time estimate: sized by bytes, timed by this machine's embed speed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# pallets/flask as measured in vm/: 89 files, 593,455 bytes, 919 chunks,
# 5.2 min wall on an 8-CPU container (setup calibration 1.763 t/s,
# real embed 2.95 chunk/s).
FLASK_FILES = 89
FLASK_BYTES = 593_455
FLASK_WALL_S = 312.0


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "ce-home"
    h.mkdir()
    monkeypatch.setenv("CTX_HOME", str(h))
    return h


def _calibrated(monkeypatch, tps: float | None) -> None:
    from types import SimpleNamespace

    profile = None if tps is None else SimpleNamespace(texts_per_sec=tps)
    monkeypatch.setattr("pipeline.accel.load_accel", lambda *a, **k: profile)


def test_calibrated_only_range_brackets_real_flask_time(home, monkeypatch) -> None:
    from pipeline.workload import estimate_init_seconds

    _calibrated(monkeypatch, 1.763)
    lo, hi = estimate_init_seconds(FLASK_FILES, FLASK_BYTES)
    assert lo <= FLASK_WALL_S <= hi


def test_measured_speed_narrows_range_and_wins_over_calibration(home, monkeypatch) -> None:
    from pipeline.workload import estimate_init_seconds, record_machine_embed_cps

    _calibrated(monkeypatch, 1.763)
    record_machine_embed_cps(chunks=919, seconds=919 / 2.95)
    lo, hi = estimate_init_seconds(FLASK_FILES, FLASK_BYTES)
    assert lo <= FLASK_WALL_S <= hi
    assert hi / lo < 1.6
    data = json.loads((home / "embed_throughput.json").read_text(encoding="utf-8"))
    assert data["cps"] == pytest.approx(2.95, abs=0.01)


@pytest.mark.parametrize(
    ("files", "nbytes", "cps", "source_tps", "wall_s"),
    [
        # Live vm/ runs: flask with calibration only, requests after flask measured speed.
        (89, 593_455, None, 1.763, 324.6),
        (50, 488_927, 2.967, 1.763, 226.1),
    ],
)
def test_live_runs_fall_inside_range(home, monkeypatch, files, nbytes, cps, source_tps, wall_s) -> None:
    from pipeline.workload import estimate_init_seconds, record_machine_embed_cps

    _calibrated(monkeypatch, source_tps)
    if cps:
        record_machine_embed_cps(chunks=1000, seconds=1000 / cps)
    lo, hi = estimate_init_seconds(files, nbytes)
    assert lo <= wall_s <= hi


def test_tiny_samples_are_ignored(home, monkeypatch) -> None:
    from pipeline.workload import machine_embed_cps, record_machine_embed_cps

    _calibrated(monkeypatch, None)
    record_machine_embed_cps(chunks=10, seconds=1.0)
    assert machine_embed_cps() == (None, "none")


def test_no_speed_known_returns_none(home, monkeypatch) -> None:
    from pipeline.workload import estimate_init_seconds

    _calibrated(monkeypatch, None)
    assert estimate_init_seconds(FLASK_FILES, FLASK_BYTES) is None


def test_format_index_eta_uses_bytes_when_given(home, monkeypatch) -> None:
    from pipeline.cli_ui import format_index_eta

    _calibrated(monkeypatch, 1.763)
    eta = format_index_eta(FLASK_FILES, total_bytes=FLASK_BYTES)
    assert eta != "~1 min"
    assert "min" in eta


# tiangolo/fastapi on an Apple M5 (MLX): 2,873 files (1,699 .md), 16.8 MB, of
# which 12.6 MB is docs; 7,435 chunks in 132 s wall at ~72 chunk/s, with ~29 s
# of non-embed time. The byte-only model said ~8–11 min.
FASTAPI = dict(files=2873, nbytes=16_834_616, doc_files=1699, doc_bytes=12_627_873, wall_s=132.1)


def test_docs_count_one_chunk_each(home, monkeypatch) -> None:
    from pipeline.workload import estimate_init_seconds, record_machine_embed_cps

    _calibrated(monkeypatch, None)
    record_machine_embed_cps(chunks=1000, seconds=1000 / 72.0)
    with_docs = estimate_init_seconds(
        FASTAPI["files"], FASTAPI["nbytes"],
        doc_files=FASTAPI["doc_files"], doc_bytes=FASTAPI["doc_bytes"],
    )
    bytes_only = estimate_init_seconds(FASTAPI["files"], FASTAPI["nbytes"])
    assert with_docs[1] < bytes_only[0]


def test_measured_overhead_brackets_fastapi_on_apple_silicon(home, monkeypatch) -> None:
    from pipeline.workload import (
        estimate_init_seconds,
        record_machine_embed_cps,
        record_machine_index_overhead,
    )

    _calibrated(monkeypatch, None)
    record_machine_embed_cps(chunks=1000, seconds=1000 / 72.0)
    record_machine_index_overhead(files=2873, seconds=29.0)
    lo, hi = estimate_init_seconds(
        FASTAPI["files"], FASTAPI["nbytes"],
        doc_files=FASTAPI["doc_files"], doc_bytes=FASTAPI["doc_bytes"],
    )
    assert lo <= FASTAPI["wall_s"] <= hi


def test_overhead_and_cps_share_the_file(home, monkeypatch) -> None:
    from pipeline.workload import (
        machine_embed_cps,
        machine_per_file_overhead_s,
        record_machine_embed_cps,
        record_machine_index_overhead,
        INIT_PER_FILE_OVERHEAD_S,
    )

    _calibrated(monkeypatch, None)
    record_machine_index_overhead(files=50, seconds=10.0)
    assert machine_per_file_overhead_s() == INIT_PER_FILE_OVERHEAD_S
    record_machine_index_overhead(files=1000, seconds=10.0)
    record_machine_embed_cps(chunks=1000, seconds=10.0)
    assert machine_per_file_overhead_s() == pytest.approx(0.01)
    assert machine_embed_cps() == (pytest.approx(100.0), "measured")


def test_scope_doc_split(tmp_path: Path) -> None:
    from pipeline.incremental import preflight_index_scope, scope_doc_split

    (tmp_path / "a.py").write_bytes(b"x = 1\n" * 100)
    (tmp_path / "README.md").write_bytes(b"# hi\n" * 10)
    preflight_index_scope(tmp_path, confirm=True)
    assert scope_doc_split(tmp_path) == (1, 50)


def test_preflight_remembers_scope_bytes(tmp_path: Path) -> None:
    from pipeline.incremental import preflight_index_scope, scope_bytes

    (tmp_path / "a.py").write_bytes(b"x = 1\n" * 100)
    (tmp_path / "b.py").write_bytes(b"y = 2\n")
    n = preflight_index_scope(tmp_path, confirm=True)
    assert n == 2
    assert scope_bytes(tmp_path) == 606
