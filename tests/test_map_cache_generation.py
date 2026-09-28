"""Issue 1: map caches are keyed on the engine's index generation.

An agent edits, the engine publishes (generation bump), the agent re-maps the
same query to confirm. Both map caches (process-local and session-store) must
miss on the new generation and hit on an unchanged repeat.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import enroll_test_repo

PID = "ce_mapgen1234567890abcdef12345678"


@pytest.fixture(autouse=True)
def _fresh_caches():
    from pipeline.index_generation import reset_for_tests
    from pipeline.map_result_cache import clear_map_cache

    reset_for_tests()
    clear_map_cache()
    yield
    reset_for_tests()
    clear_map_cache()


def _repo(tmp_path: Path, home: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    enroll_test_repo(repo, home=home, project_id=PID)
    return repo


def _dense_payload(cards: list[dict]) -> dict:
    return {
        "ok": True,
        "dense": True,
        "retrieve_mode": "D_channel_best",
        "timings": {"dense": True, "retrieve_mode": "D_channel_best"},
        "cards": cards,
    }


def test_stamp_roundtrip_is_monotonic_per_epoch(tmp_path, _isolate_scubiee_home):
    from pipeline.index_generation import read_token, write_stamp

    repo = _repo(tmp_path, _isolate_scubiee_home)
    assert read_token(repo) is None  # no engine has published yet

    assert write_stamp(PID, 5, epoch="e1")
    assert read_token(repo) == "e1:5"
    # A slower, older publish finishing late must not re-validate gen-4 entries.
    assert not write_stamp(PID, 4, epoch="e1")
    assert read_token(repo) == "e1:5"
    # Engine restart / runtime recreated: counter restarts, epoch differs.
    assert write_stamp(PID, 1, epoch="e2")
    assert read_token(repo) == "e2:1"


def test_torn_or_missing_stamp_disables_cache(tmp_path, _isolate_scubiee_home):
    from pipeline.index_generation import read_token, stamp_path

    repo = _repo(tmp_path, _isolate_scubiee_home)
    path = stamp_path(PID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")  # reader raced a writer
    assert read_token(repo) is None


def test_process_cache_misses_after_generation_bump():
    from pipeline.map_result_cache import get_map_cached, put_map_cached

    put_map_cached(repo="/r", query="q one", fingerprint="e1:3", payload=_dense_payload([{"file": "a.py"}]))
    hit = get_map_cached(repo="/r", query="q one", fingerprint="e1:3")
    assert hit is not None and hit["cache"] in {"last", "hit"}

    # The engine's stamp only moves forward per epoch, so the old key is never
    # asked for again; it ages out of _CACHE by TTL / size cap.
    assert get_map_cached(repo="/r", query="q one", fingerprint="e1:4") is None


def test_no_token_means_no_cache():
    from pipeline.map_result_cache import get_map_cached, put_map_cached

    put_map_cached(repo="/r", query="q", fingerprint=None, payload=_dense_payload([{"file": "a.py"}]))
    assert get_map_cached(repo="/r", query="q", fingerprint=None) is None
    put_map_cached(repo="/r", query="q", fingerprint="e1:1", payload=_dense_payload([{"file": "a.py"}]))
    assert get_map_cached(repo="/r", query="q", fingerprint=None) is None


def test_recent_map_cards_only_from_current_generation(tmp_path, _isolate_scubiee_home):
    from pipeline.index_generation import write_stamp
    from pipeline.map_result_cache import get_recent_map_cards, put_map_cached

    repo = _repo(tmp_path, _isolate_scubiee_home)
    write_stamp(PID, 1, epoch="e1")
    put_map_cached(repo=str(repo), query="q", fingerprint="e1:1", payload=_dense_payload([{"file": "old.py"}]))
    assert [c["file"] for c in get_recent_map_cards(repo=str(repo))] == ["old.py"]
    write_stamp(PID, 2, epoch="e1")
    assert get_recent_map_cards(repo=str(repo)) == []


def test_runtime_publish_writes_stamp(tmp_path, _isolate_scubiee_home):
    from pipeline.ce_service import RuntimeManager
    from pipeline.index_generation import read_token
    from pipeline.repo_runtime import RepoRuntime

    repo = _repo(tmp_path, _isolate_scubiee_home)
    runtime = RepoRuntime(PID, repo)
    runtime.generation = 3
    RuntimeManager._stamp_generation(runtime)
    assert read_token(repo) == f"{runtime.epoch}:3"
    # Each runtime gets its own epoch, so a restarted counter never collides.
    assert RepoRuntime(PID, repo).epoch != runtime.epoch


def test_hot_publish_advances_stamp(tmp_path, _isolate_scubiee_home):
    from pipeline.ce_service import RuntimeManager
    from pipeline.index_generation import read_token
    from pipeline.repo_runtime import RepoRuntime

    class _Engine:
        texts = ["a"]

        def apply_chunk_delta(self, records, matrix, **_kw):
            self.texts = self.texts + list(records)
            return {"chunks_before": 1, "chunks_after": len(self.texts), "appended": len(records)}

    class _Delta:
        append_only = True
        records = ["b"]
        matrix = object()
        base_chunk_count = 1

    repo = _repo(tmp_path, _isolate_scubiee_home)
    manager = RuntimeManager()
    runtime = RepoRuntime(PID, repo, engine=_Engine(), generation=4)
    out = manager._hot_publish_runtime(runtime, {}, _Delta())
    assert out is not None and out["generation"] == 5
    assert read_token(repo) == f"{runtime.epoch}:5"


def test_session_store_cache_is_token_keyed(tmp_path):
    from pipeline.mcp_locate import _map_cache_get, _map_cache_put
    from pipeline.session_store import load_store

    repo = tmp_path / "proj"
    (repo / ".scubiee").mkdir(parents=True)
    cards = [{"file": "a.py"}]
    _map_cache_put(repo, "q", 8, cards, session_id="s", token="e1:2")
    store = load_store(repo, session_id="s")
    assert _map_cache_get(store, "q", 8, token="e1:2") == cards
    assert _map_cache_get(store, "q", 8, token="e1:3") is None
    # Entries written before generation keying carry no token: never served.
    store["map_cache"]["q"].pop("token")
    assert _map_cache_get(store, "q", 8, token="e1:2") is None


def test_map_tool_remap_after_publish_is_fresh(tmp_path, monkeypatch, _isolate_scubiee_home):
    """map(Q) -> publish -> map(Q) returns the new cards; an unchanged repeat hits."""
    pytest.importorskip("mcp")
    from pipeline import locate as loc
    from pipeline.index_generation import write_stamp
    from pipeline.map_result_cache import clear_map_cache

    repo = _repo(tmp_path, _isolate_scubiee_home)
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    monkeypatch.chdir(repo)
    for key in ("CURSOR_PROJECT_DIR", "WORKSPACE_FOLDER", "INIT_CWD", "PWD", "CTX_PROJECT_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    monkeypatch.setattr("pipeline.mcp_locate._note_locate_streak", lambda *_a, **_k: None)
    monkeypatch.setattr("pipeline.mcp_lifecycle.locate_worker_prewarm_done", lambda: True)

    served: dict = {"hits": [], "calls": 0}

    def _fake_hits(*_a, **_k):
        served["calls"] += 1
        loc.LAST_SEARCH_META.clear()
        loc.LAST_SEARCH_META.update(
            {"dense": True, "retrieve_mode": "D_channel_best",
             "timings": {"dense": True, "retrieve_mode": "D_channel_best"}}
        )
        return [dict(h) for h in served["hits"]]

    monkeypatch.setattr(loc, "_search_hits", _fake_hits)

    def _hit(sym: str, line: int) -> dict:
        return {"file": "pkg/mod.py", "start_line": line, "end_line": line + 3,
                "score": 9.0, "why": f"def {sym}(payload):", "source": "D_channel_best"}

    from pipeline.mcp_locate import create_mcp

    map_fn = create_mcp(name="map-gen-test")._tool_manager._tools["map"].fn
    query = "zz_token_handler map staleness probe symbol payload"

    def _map() -> dict:
        return json.loads(map_fn(query=query, k=6, session_id="gen-test"))

    served["hits"] = [_hit("old_handler", 1)]
    write_stamp(PID, 1, epoch="e1")
    first = _map()
    assert first["ok"] and served["calls"] == 1 and "cache" not in first
    repeat = _map()
    assert repeat["cache"] in {"last", "hit"} and served["calls"] == 1

    # Edit -> engine publishes generation 2.
    served["hits"] = [_hit("zz_token_handler", 20), _hit("old_handler", 1)]
    write_stamp(PID, 2, epoch="e1")
    fresh = _map()
    assert served["calls"] == 2 and "cache" not in fresh
    assert any("zz_token_handler" in json.dumps(c) for c in fresh["cards"])
    again = _map()
    assert again["cache"] in {"last", "hit"} and served["calls"] == 2

    # Session-store duplicate path (new MCP worker / process cache gone).
    clear_map_cache()
    sess = _map()
    assert sess["cache"] == "session" and served["calls"] == 2
    served["hits"] = [_hit("newest_handler", 40)]
    write_stamp(PID, 3, epoch="e1")
    clear_map_cache()
    after = _map()
    assert served["calls"] == 3 and "cache" not in after
    assert any("newest_handler" in json.dumps(c) for c in after["cards"])
