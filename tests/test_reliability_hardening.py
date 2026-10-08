"""Reliability-hardening tests (from the adversarial-stress follow-ups).

Covers three fixes:
  1. /health disk-touch TTL cache (lock-free hot path under embed load)
  2. delete-before-add drain ordering (fast rename/delete prune)
  3. pre-chunk oversized-file guard (skip pathological huge files cheaply)

Offline; no live engine/embedder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import enroll_test_repo


# ---- Issue 2: deletes drain before adds -------------------------------------

@pytest.fixture
def _enrolled(tmp_path, monkeypatch):
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_reliab1234567890abcdef0")
    monkeypatch.setattr(
        "pipeline.sync_loop.BackgroundSyncLoop._clients_active", lambda self: False
    )
    return tmp_path


def test_deletes_ordered_before_adds(_enrolled, monkeypatch):
    from pipeline.sync_loop import BackgroundSyncLoop

    monkeypatch.delenv("CTX_DELETES_FIRST", raising=False)  # default on
    loop = BackgroundSyncLoop(_enrolled, debounce_ms=0)
    (_enrolled / "pkg").mkdir(parents=True, exist_ok=True)
    (_enrolled / "pkg" / "present.py").write_text("x=1\n", encoding="utf-8")
    # mix: one present (add), one gone (delete)
    ordered = loop._additions_before_deletions(["pkg/present.py", "pkg/gone.py"])
    assert ordered == ["pkg/gone.py", "pkg/present.py"], "delete must come first"


def test_deletes_first_can_be_disabled(_enrolled, monkeypatch):
    from pipeline.sync_loop import BackgroundSyncLoop

    monkeypatch.setenv("CTX_DELETES_FIRST", "0")
    loop = BackgroundSyncLoop(_enrolled, debounce_ms=0)
    (_enrolled / "pkg").mkdir(parents=True, exist_ok=True)
    (_enrolled / "pkg" / "present.py").write_text("x=1\n", encoding="utf-8")
    ordered = loop._additions_before_deletions(["pkg/present.py", "pkg/gone.py"])
    assert ordered == ["pkg/present.py", "pkg/gone.py"], "rollback = old adds-first order"


# ---- Issue 3: oversized-file guard ------------------------------------------

def test_oversized_file_detection_by_lines(tmp_path, monkeypatch):
    import importlib
    import pipeline.incremental as inc

    monkeypatch.setenv("CTX_MAX_FILE_LINES", "100")
    monkeypatch.setenv("CTX_MAX_FILE_BYTES", "0")  # disable byte cap, test lines
    importlib.reload(inc)
    try:
        big = tmp_path / "huge.py"
        big.write_text("\n".join(f"x = {i}" for i in range(500)) + "\n", encoding="utf-8")
        small = tmp_path / "small.py"
        small.write_text("x = 1\n", encoding="utf-8")
        assert inc._oversized_file(big) is not None
        assert "lines" in inc._oversized_file(big)
        assert inc._oversized_file(small) is None
    finally:
        monkeypatch.delenv("CTX_MAX_FILE_LINES", raising=False)
        monkeypatch.delenv("CTX_MAX_FILE_BYTES", raising=False)
        importlib.reload(inc)


def test_oversized_file_detection_by_bytes(tmp_path, monkeypatch):
    import importlib
    import pipeline.incremental as inc

    monkeypatch.setenv("CTX_MAX_FILE_BYTES", "500")
    monkeypatch.setenv("CTX_MAX_FILE_LINES", "0")
    importlib.reload(inc)
    try:
        big = tmp_path / "fat.py"
        big.write_text("y = 2  # " + ("padding " * 200) + "\n", encoding="utf-8")
        assert inc._oversized_file(big) is not None
        assert "bytes" in inc._oversized_file(big)
    finally:
        monkeypatch.delenv("CTX_MAX_FILE_BYTES", raising=False)
        monkeypatch.delenv("CTX_MAX_FILE_LINES", raising=False)
        importlib.reload(inc)


def test_oversized_guard_disabled_when_zero(tmp_path, monkeypatch):
    import importlib
    import pipeline.incremental as inc

    monkeypatch.setenv("CTX_MAX_FILE_LINES", "0")
    monkeypatch.setenv("CTX_MAX_FILE_BYTES", "0")
    importlib.reload(inc)
    try:
        big = tmp_path / "huge.py"
        big.write_text("\n".join(f"x = {i}" for i in range(50000)) + "\n", encoding="utf-8")
        assert inc._oversized_file(big) is None  # both caps off => never oversized
    finally:
        monkeypatch.delenv("CTX_MAX_FILE_LINES", raising=False)
        monkeypatch.delenv("CTX_MAX_FILE_BYTES", raising=False)
        importlib.reload(inc)


# ---- Issue 1: health disk-touch TTL cache -----------------------------------

def test_health_disk_snapshot_is_ttl_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_HEALTH_CACHE_TTL_S", "60")
    from pipeline.ce_service import RuntimeManager

    rm = RuntimeManager()
    rm.repo = tmp_path  # unenrolled repo -> peek_project returns None, cheap

    calls = {"n": 0}
    import pipeline.project_id as pj
    real_peek = pj.peek_project

    def counting_peek(repo):
        calls["n"] += 1
        return real_peek(repo)

    monkeypatch.setattr("pipeline.project_id.peek_project", counting_peek)

    s1 = rm._health_disk_snapshot()
    s2 = rm._health_disk_snapshot()
    s3 = rm._health_disk_snapshot()
    # three snapshot calls, but peek_project ran at most ONCE within the TTL
    assert calls["n"] <= 1, f"peek_project ran {calls['n']} times; cache not used"
    assert s1 is s2 is s3  # same cached object within TTL


def test_health_cache_refreshes_after_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_HEALTH_CACHE_TTL_S", "0")  # TTL 0 => always refresh
    from pipeline.ce_service import RuntimeManager

    rm = RuntimeManager()
    rm.repo = tmp_path
    calls = {"n": 0}
    import pipeline.project_id as pj
    real_peek = pj.peek_project

    def counting_peek(repo):
        calls["n"] += 1
        return real_peek(repo)

    monkeypatch.setattr("pipeline.project_id.peek_project", counting_peek)
    rm._health_disk_snapshot()
    rm._health_disk_snapshot()
    assert calls["n"] >= 2, "TTL=0 must refresh every call"
