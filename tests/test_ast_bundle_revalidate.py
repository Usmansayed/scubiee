"""BUG-A: pack's AST bundle must be revalidated after edits (stale-while-revalidate).

map searches the live index; pack resolves seeds against a disk AST bundle
accepted stale (BETA-02) and, before this fix, never rebaked. So map suggested
seeds pack could not resolve. The keeper now rebakes the bundle in the background
when the corpus fingerprint moves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import context_trace as ct


def _seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    return repo


def test_bundle_is_stale_when_missing_then_fresh_after_bake(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    assert ct.ast_bundle_is_stale(repo) is True, "no bundle yet -> stale"
    out = ct.hydrate_ast_bundle(repo, bake_on_miss=True)
    assert out.get("ok"), out
    assert ct._repo_bundle_path(repo).is_file()
    assert ct.ast_bundle_is_stale(repo) is False, "just baked -> fresh"


def test_edit_makes_bundle_stale_and_refresh_rebakes(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    ct.hydrate_ast_bundle(repo, bake_on_miss=True)
    assert ct.ast_bundle_is_stale(repo) is False

    # Add a brand-new symbol the baked bundle cannot know about.
    (repo / "pkg" / "b.py").write_text(
        "def beta_new_symbol():\n    return 2\n", encoding="utf-8"
    )
    assert ct.ast_bundle_is_stale(repo) is True, "edited corpus -> stale"

    # In-process force rebake (block=True). Uses _load_repo(force_bake=True),
    # not the child, so the test does not depend on spawning an interpreter.
    ct._CACHE.clear()
    ct._BUNDLE_RAW_CACHE.clear()
    out = ct.hydrate_ast_bundle(repo, force=True)
    assert out.get("ok") and out.get("source") == "bake_forced", out
    assert ct.ast_bundle_is_stale(repo) is False, "rebake cleared staleness"

    rt = ct._load_repo(repo)
    syms = {n.symbol for n in rt.nodes.values() if n.file.endswith("pkg/b.py")}
    assert "beta_new_symbol" in syms, "the new symbol is now resolvable for pack"


def test_refresh_if_stale_single_flight_and_coalesced(tmp_path: Path, monkeypatch) -> None:
    repo = _seed_repo(tmp_path)
    ct.hydrate_ast_bundle(repo, bake_on_miss=True)
    (repo / "pkg" / "c.py").write_text("def gamma():\n    return 3\n", encoding="utf-8")

    calls = {"n": 0}

    def _fake_spawn(root, *, force=False):
        calls["n"] += 1
        # Emulate the child writing a fresh bundle for the current corpus.
        ct._CACHE.clear()
        ct._BUNDLE_RAW_CACHE.clear()
        ct._load_repo(Path(root), force_bake=True)
        return {"ok": True}

    monkeypatch.setattr(ct, "_spawn_ast_bake", _fake_spawn)
    key = str(repo.resolve())
    ct._REFRESH_LAST_FP.pop(key, None)

    first = ct.refresh_ast_bundle_if_stale(repo, block=True)
    assert first.get("ok") and not first.get("skipped"), first
    assert calls["n"] == 1

    # Corpus unchanged since the rebake -> coalesced, no second bake.
    second = ct.refresh_ast_bundle_if_stale(repo, block=True)
    assert second.get("skipped") == "fresh", second
    assert calls["n"] == 1, "no rebake when the fingerprint has not moved"


def test_refresh_spawns_a_gil_isolated_child(tmp_path: Path, monkeypatch) -> None:
    """The revalidate rebakes in a fresh interpreter (GIL-isolated from the
    engine's search/catch-up load — PERF-1), which writes the disk bundle."""
    repo = _seed_repo(tmp_path)
    ct.hydrate_ast_bundle(repo, bake_on_miss=True)
    (repo / "pkg" / "e.py").write_text("def epsilon_new():\n    return 5\n", encoding="utf-8")

    spawned = {"n": 0}

    def _fake_spawn(root, *, force=False):
        spawned["n"] += 1
        ct._CACHE.clear()
        ct._BUNDLE_RAW_CACHE.clear()
        ct._load_repo(Path(root), force_bake=True)  # emulate the child's disk write
        return {"ok": True}

    monkeypatch.setattr(ct, "_spawn_ast_bake", _fake_spawn)
    ct._REFRESH_LAST_FP.pop(str(repo.resolve()), None)
    out = ct.refresh_ast_bundle_if_stale(repo, block=True)
    assert out.get("ok") and out.get("source") == "revalidate", out
    assert spawned["n"] == 1
    rt = ct._load_repo(repo)
    assert any(n.symbol == "epsilon_new" for n in rt.nodes.values())


def test_refresh_skips_when_already_fresh(tmp_path: Path, monkeypatch) -> None:
    repo = _seed_repo(tmp_path)
    ct.hydrate_ast_bundle(repo, bake_on_miss=True)
    ct._REFRESH_LAST_FP.pop(str(repo.resolve()), None)

    def _boom(*_a, **_k):
        raise AssertionError("must not rebake a fresh bundle")

    monkeypatch.setattr(ct, "_spawn_ast_bake", _boom)
    out = ct.refresh_ast_bundle_if_stale(repo, block=True)
    assert out.get("skipped") == "fresh", out


def test_keeper_starts_a_revalidate_thread(tmp_path: Path, monkeypatch) -> None:
    from conftest import enroll_test_repo

    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_astreval1234567890abcdef012")
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)

    called = {"n": 0}
    monkeypatch.setattr(
        "pipeline.context_trace.refresh_ast_bundle_if_stale",
        lambda *_a, **_k: called.__setitem__("n", called["n"] + 1) or {"ok": True, "skipped": "fresh"},
    )
    assert loop._start_ast_revalidate() is True
    t = loop._ast_revalidate_thread
    assert t is not None
    t.join(timeout=10)
    assert called["n"] == 1


def test_worker_cache_reloads_when_disk_bundle_is_rebaked(tmp_path: Path) -> None:
    """Second half of BUG-A: a long-lived worker's in-memory trace must drop when
    a background revalidate rewrote the disk bundle, not wait out the 600s TTL."""
    import time as _time

    repo = _seed_repo(tmp_path)
    ct._CACHE.clear()
    ct._BUNDLE_RAW_CACHE.clear()
    ct.hydrate_ast_bundle(repo, bake_on_miss=True)
    rt1 = ct._load_repo(repo)
    assert not any(n.file.endswith("pkg/d.py") for n in rt1.nodes.values())
    key = ct._repo_cache_key(repo)
    assert key in ct._CACHE, "in-memory trace is cached"

    # Add a symbol and force a disk rebake (what the background child does).
    _time.sleep(0.02)
    (repo / "pkg" / "d.py").write_text("def delta_sym():\n    return 4\n", encoding="utf-8")
    ct._BUNDLE_RAW_CACHE.clear()
    ct.hydrate_ast_bundle(repo, force=True)  # rewrites the disk bundle

    # Same process, cache still populated, TTL not elapsed — but the disk mtime
    # moved, so _load_repo must rebuild instead of serving the stale in-memory rt.
    rt2 = ct._load_repo(repo)
    assert any(n.symbol == "delta_sym" for n in rt2.nodes.values()), (
        "worker kept the pre-rebake nodes despite a fresh disk bundle"
    )
