"""Unit coverage for MCP reliability: locate.state + idle busy veto + idle merge-max."""

from __future__ import annotations

from pathlib import Path


def test_derive_locate_state_matrix() -> None:
    from pipeline.sync_status import derive_locate_state

    ready = derive_locate_state(
        healthy=True,
        soft_search_ready=True,
        warm_state="ready",
        project_bound=True,
    )
    assert ready["state"] == "ready"
    assert ready["should_use"] is True

    err = derive_locate_state(
        healthy=True,
        soft_search_ready=False,
        warm_state="error",
        warm_error="DML provider missing",
        project_bound=False,
    )
    assert err["state"] == "error"
    assert err["should_use"] is False
    assert err["should_retry"] is False

    unbound = derive_locate_state(
        healthy=True,
        soft_search_ready=False,
        warm_state="ready",
        project_bound=False,
    )
    assert unbound["state"] == "unbound"

    indexing = derive_locate_state(
        healthy=True,
        soft_search_ready=False,
        warm_state="indexing",
        project_bound=True,
        index_usable=False,
    )
    assert indexing["state"] == "indexing"
    assert indexing["should_retry"] is True

    starting = derive_locate_state(
        healthy=False,
        soft_search_ready=False,
        warm_state=None,
        project_bound=False,
    )
    assert starting["state"] == "starting"


def test_derive_agent_ready_follows_locate_error() -> None:
    from pipeline.sync_status import derive_agent_ready, derive_locate_state

    loc = derive_locate_state(
        healthy=True,
        soft_search_ready=False,
        warm_state="error",
        warm_error="accel missing",
        project_bound=True,
    )
    # Legacy label stays warming; locate.state is the truth.
    assert (
        derive_agent_ready(
            healthy=True,
            soft_search_ready=False,
            sync_state="ready",
            ready=False,
            syncing=False,
            overlay_ready=False,
            locate=loc,
        )
        == "warming"
    )
    assert loc["state"] == "error"


def test_indexing_postpones_armed_disconnect_until_busy_lifts(
    monkeypatch, tmp_path
) -> None:
    """MCP blip during index must not retire the engine the instant indexing ends."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "25")
    monkeypatch.setenv("CTX_ENGINE_TRANSITION_DEBOUNCE_S", "0")
    from pipeline import lifecycle_runtime as life

    class _Gov:
        indexing = True

    monkeypatch.setattr("pipeline.memory_governor.get_governor", lambda: _Gov())
    life.register_client("mcp:1", pid=1, now=100.0)
    life.unregister_client("mcp:1", now=100.0)
    busy = life.apply_idle_policy(now=200.0)
    assert busy.get("action") == "busy"
    _Gov.indexing = False
    assert life.should_idle_stop(now=210.0) is False
    assert life.should_idle_stop(now=226.0) is True


def test_apply_idle_policy_busy_while_indexing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_ENGINE_IDLE_S", "1")
    monkeypatch.setenv("CTX_ENGINE_TRANSITION_DEBOUNCE_S", "0")
    from pipeline import lifecycle_runtime as life

    class _Gov:
        indexing = True

    monkeypatch.setattr(
        "pipeline.memory_governor.get_governor",
        lambda: _Gov(),
    )
    life.note_activity(now=100.0)
    # No clients + past idle window, but indexing vetoes stop.
    result = life.apply_idle_policy(now=200.0)
    assert result.get("action") == "busy"
    assert result.get("reason") == "indexing"
    assert life.should_idle_stop(now=200.0) is False


def test_merge_idle_env_max_never_clobbers_higher() -> None:
    from pipeline.mcp_install import _merge_idle_env_max, server_entry

    env = server_entry(None).get("env") or {}
    assert env["CTX_DISCONNECT_DEBOUNCE_S"] == "10"
    assert env["CTX_ENGINE_IDLE_S"] == "10"

    dst = {"CTX_ENGINE_IDLE_S": "10", "CTX_ENGINE_TRANSITION_DEBOUNCE_S": "5"}
    _merge_idle_env_max(dst, {"CTX_ENGINE_IDLE_S": "900", "CTX_ENGINE_TRANSITION_DEBOUNCE_S": "120"})
    # Disconnect unload knobs are not sticky-raised from old 300s/900s; transition debounce still takes max.
    assert dst["CTX_ENGINE_IDLE_S"] == "10"
    assert dst["CTX_ENGINE_TRANSITION_DEBOUNCE_S"] == "120"

    dst2 = {"CTX_ENGINE_IDLE_S": "10", "CTX_ENGINE_TRANSITION_DEBOUNCE_S": "60"}
    _merge_idle_env_max(dst2, {"CTX_ENGINE_IDLE_S": "10", "CTX_ENGINE_TRANSITION_DEBOUNCE_S": "5"})
    assert dst2["CTX_ENGINE_IDLE_S"] == "10"
    assert dst2["CTX_ENGINE_TRANSITION_DEBOUNCE_S"] == "60"


def test_publish_manifest_recovers_checksum_mismatch(tmp_path: Path) -> None:
    from pipeline.artifact_guard import (
        MANIFEST_NAME,
        heal_checksum_mismatch,
        publish_manifest,
        validate_manifest,
    )

    store = tmp_path / "store"
    store.mkdir()
    artifact = store / "chunks.jsonl"
    artifact.write_text("a\n", encoding="utf-8")
    publish_manifest(store, [artifact])
    assert validate_manifest(store).get("ok") is True

    artifact.write_text("corrupted\n", encoding="utf-8")
    bad = validate_manifest(store)
    assert bad.get("ok") is False
    assert bad.get("reason") == "checksum_mismatch"

    # Without a real indexable repo, heal must refuse (keep bad manifest).
    report = heal_checksum_mismatch(store, root=None)
    assert report.get("ok") is False
    assert report.get("healed") is False
    assert (store / MANIFEST_NAME).is_file()
    assert validate_manifest(store).get("reason") == "checksum_mismatch"


def test_bridge_error_message_never_empty() -> None:
    empty = RuntimeError("")
    filled = f"{type(empty).__name__}: {str(empty) or repr(empty)}"
    assert filled.startswith("RuntimeError:")
    assert "RuntimeError" in filled
    assert filled != "RuntimeError: "
