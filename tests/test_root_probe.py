"""Root-probe idle gate tests (no embedder)."""

from __future__ import annotations

import json
import time
from pathlib import Path

from pipeline.merkle import file_sha256, root_hash, save_snapshot
from pipeline.root_probe import root_probe
from pipeline.store import PipelineStore


def _seed_store(tmp_path: Path, files: dict[str, str]) -> PipelineStore:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    store = PipelineStore(tmp_path, base_dir=tmp_path / ".ce")
    hashes = {rel: file_sha256(tmp_path / rel) for rel in files}
    store.save_merkle(hashes)
    store.save_meta({"fast": True, "fast_roots": ["pkg/"], "git_head": None})
    return store


def test_root_probe_clean(tmp_path: Path):
    store = _seed_store(tmp_path, {"pkg/a.py": "x=1\n"})
    r = root_probe(tmp_path, base_dir=store.base, discover_newcomers=False)
    assert r.clean
    assert r.changed_count == 0
    assert r.files_checked == 1


def test_root_probe_detects_edit(tmp_path: Path):
    store = _seed_store(tmp_path, {"pkg/a.py": "x=1\n"})
    time.sleep(0.05)
    (tmp_path / "pkg" / "a.py").write_text("x=2\n", encoding="utf-8")
    r = root_probe(tmp_path, base_dir=store.base, discover_newcomers=False)
    assert not r.clean
    assert "pkg/a.py" in r.modified


def test_root_probe_detects_delete(tmp_path: Path):
    store = _seed_store(tmp_path, {"pkg/a.py": "x=1\n", "pkg/b.py": "y=1\n"})
    (tmp_path / "pkg" / "b.py").unlink()
    r = root_probe(tmp_path, base_dir=store.base, discover_newcomers=False)
    assert not r.clean
    assert "pkg/b.py" in r.removed


def test_root_probe_ignores_venv_junk(tmp_path: Path):
    store = _seed_store(tmp_path, {"pkg/a.py": "x=1\n"})
    junk = tmp_path / ".venv-proof" / "Lib" / "site-packages" / "foo.py"
    junk.parent.mkdir(parents=True)
    junk.write_text("evil=1\n", encoding="utf-8")
    r = root_probe(tmp_path, base_dir=store.base, discover_newcomers=True)
    assert r.clean
    assert not any("venv" in p for p in r.added)


def test_keeper_tick_root_clean_no_refresh(tmp_path: Path, monkeypatch):
    from pipeline.sync_loop import BackgroundSyncLoop

    store = _seed_store(tmp_path, {"pkg/a.py": "x=1\n"})
    called = {"n": 0}

    def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("incremental_sync must not run on root clean")

    monkeypatch.setattr("pipeline.incremental.incremental_sync", _boom)
    loop = BackgroundSyncLoop(tmp_path)
    # Point store via monkeypatch on PipelineStore used inside root_probe —
    # root_probe uses PipelineStore(repo) default home path; use base_dir via
    # wrapping root_probe instead.
    from pipeline import root_probe as rp

    real = rp.root_probe

    def _probe(repo, **kw):
        kw.setdefault("base_dir", store.base)
        kw.setdefault("discover_newcomers", False)
        return real(repo, **kw)

    monkeypatch.setattr("pipeline.root_probe.root_probe", _probe)
    monkeypatch.setattr("pipeline.sync_loop.root_probe", _probe, raising=False)
    # keeper imports root_probe inside method
    monkeypatch.setattr(
        "pipeline.root_probe.root_probe",
        lambda repo, **kw: real(repo, base_dir=store.base, discover_newcomers=False),
    )
    out = loop.keeper_tick(reason="test")
    assert out.get("strategy") == "root_clean"
    assert out.get("refreshed") is False
    assert called["n"] == 0
