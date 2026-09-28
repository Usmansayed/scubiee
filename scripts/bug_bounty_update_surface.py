#!/usr/bin/env python3
"""Adversarial smoke for 0.3.26 update surfaces (idle/reconnect/adopt/debounce/force).

Exit 0 only if every check passes. Safe: uses temp CTX_HOME; may touch live
daemon only for optional --live probes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


class Suite:
    def __init__(self) -> None:
        self.failed: list[str] = []
        self.passed = 0

    def check(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passed += 1
            print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
        else:
            self.failed.append(f"{name}: {detail or 'assertion failed'}")
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def wave_defaults(s: Suite) -> None:
    from pipeline.dirty_ledger import DirtyLedger
    from pipeline.lifecycle_runtime import (
        DEFAULT_IDLE_S,
        DEFAULT_TRANSITION_DEBOUNCE_S,
        idle_seconds,
        transition_debounce_seconds,
    )
    from pipeline.memory_governor import embed_idle_demote_s
    from pipeline.sync_loop import DEFAULT_DEBOUNCE_MS, DEFAULT_REWRITE_DEBOUNCE_MS

    s.check("idle_default_15", DEFAULT_IDLE_S == 15.0, str(DEFAULT_IDLE_S))
    s.check("transition_default_15", DEFAULT_TRANSITION_DEBOUNCE_S == 15.0)
    s.check("idle_seconds_15", idle_seconds() == 15.0)
    s.check("transition_seconds_15", transition_debounce_seconds() == 15.0)
    s.check("debounce_1000", DEFAULT_DEBOUNCE_MS == 1000, str(DEFAULT_DEBOUNCE_MS))
    s.check("rewrite_debounce_2000", DEFAULT_REWRITE_DEBOUNCE_MS == 2000)
    s.check("embed_demote_tracks_idle", embed_idle_demote_s() == 15.0)
    ledger = DirtyLedger()
    s.check("ledger_defaults", ledger.debounce_ms == 1000 and ledger.rewrite_debounce_ms == 2000)


def wave_idle_policy(s: Suite, home: Path) -> None:
    os.environ["CTX_HOME"] = str(home)
    os.environ["CTX_ENGINE_IDLE_S"] = "15"
    os.environ["CTX_ENGINE_TRANSITION_DEBOUNCE_S"] = "15"

    from pipeline import lifecycle_runtime as life

    # Fresh policy
    life.save_policy(
        {
            "desired_mode": life.DESIRED_RUN,
            "last_activity": 0.0,
            "last_client_left_at": None,
        }
    )
    life.save_clients({"clients": {}})

    life.register_client("mcp:bb", pid=os.getpid(), now=100.0)
    s.check("client_blocks_idle", life.should_idle_stop(now=200.0) is False)

    life.unregister_client("mcp:bb", now=200.0)
    s.check("not_idle_at_14s", life.should_idle_stop(now=214.0) is False)
    s.check("idle_at_15s", life.should_idle_stop(now=215.0) is True)

    # Activity after leave clears leave clock
    life.register_client("mcp:bb2", pid=os.getpid(), now=300.0)
    life.unregister_client("mcp:bb2", now=300.0)
    life.note_activity(now=301.0)
    s.check(
        "activity_clears_leave",
        life.load_policy().get("last_client_left_at") is None,
    )
    s.check("activity_blocks_idle", life.should_idle_stop(now=310.0) is False)


def wave_warm_hold(s: Suite, home: Path) -> None:
    os.environ["CTX_HOME"] = str(home)
    os.environ["CTX_EMBED_IDLE_DEMOTE_S"] = "15"

    from pipeline.memory_governor import MemoryGovernor, reset_governor_for_tests

    reset_governor_for_tests()
    gov = MemoryGovernor()
    gov.desired_tier = "serve_1repo"
    gov.apply_tier("serve_1repo")
    left = 1000.0
    gov.last_semantic_at = left - 120

    import pipeline.lifecycle_runtime as life

    # Patch client count / policy via env home files
    life.save_policy(
        {
            "desired_mode": life.DESIRED_RUN,
            "last_activity": left - 120,
            "last_client_left_at": left,
        }
    )
    life.save_clients({"clients": {}})

    released: list[bool] = []

    def _rel() -> int:
        released.append(True)
        return 1

    import pipeline.engine as eng

    old = getattr(eng, "release_embedders", None)
    eng.release_embedders = _rel  # type: ignore[assignment]
    try:
        mid = gov.maybe_demote_idle(now=left + 10)
        s.check("warm_hold_mid_grace", mid is None and gov.active_tier == "serve_1repo")
        late = gov.maybe_demote_idle(now=left + 16)
        s.check(
            "demote_after_grace",
            late is not None and late.get("action") == "demote_serve",
            str(late),
        )
    finally:
        if old is not None:
            eng.release_embedders = old  # type: ignore[assignment]


def wave_adopt(s: Suite, home: Path) -> None:
    os.environ["CTX_HOME"] = str(home)
    from pipeline.mcp_hot_reload import (
        adopt_installed_package_on_connect,
        read_active_build_stamp,
        write_active_build_stamp,
    )
    from pipeline.upgrade import installed_version

    write_active_build_stamp("0.0.0-old", epoch=1.0)
    report = adopt_installed_package_on_connect()
    stamp = read_active_build_stamp() or {}
    iv = installed_version()
    s.check("adopt_ok", report.get("ok") is True, str(report))
    s.check("stamp_updated", report.get("stamp_updated") is True)
    s.check("stamp_version", stamp.get("version") == iv, f"{stamp} vs {iv}")

    report2 = adopt_installed_package_on_connect()
    s.check("adopt_idempotent", report2.get("stamp_updated") is False)
    s.check(
        "daemon_action_sane",
        report2.get("daemon", {}).get("action") in {"version_match", "restarted", "no_daemon"},
        str(report2.get("daemon")),
    )


def wave_debounce_timing(s: Suite) -> None:
    from pipeline.dirty_ledger import DirtyLedger

    ledger = DirtyLedger(debounce_ms=1000, rewrite_debounce_ms=2000)
    ledger.mark(["a.py", "b.py"], reason="write", now=0.0)
    ledger.mark(["a.py"], reason="write", now=0.5)
    due_early = ledger.due_paths(now=1.2)
    s.check("b_due_after_1s", due_early == ["b.py"], str(due_early))
    due_rewrite = ledger.due_paths(now=2.6)
    s.check("a_due_after_rewrite", "a.py" in due_rewrite, str(due_rewrite))


def wave_force_gate(s: Suite) -> None:
    from pipeline.incremental import DEFAULT_MAX_CHUNKS, IndexConfirmRequired, require_chunk_force

    require_chunk_force(DEFAULT_MAX_CHUNKS, force=False)
    try:
        require_chunk_force(DEFAULT_MAX_CHUNKS + 1, force=False)
        s.check("force_blocks_over_cap", False, "expected IndexConfirmRequired")
    except IndexConfirmRequired as exc:
        msg = str(exc).lower()
        s.check(
            "force_blocks_over_cap",
            "force" in msg or "token" in msg or "chunk" in msg,
            str(exc),
        )
    require_chunk_force(DEFAULT_MAX_CHUNKS + 1, force=True)
    s.check("force_allows_over_cap", True)


def wave_paths_polyglot(s: Suite, tmp: Path) -> None:
    from pipeline.paths import collect_index_paths

    (tmp / "a.py").write_text("x=1\n", encoding="utf-8")
    (tmp / "b.ts").write_text("const x=1\n", encoding="utf-8")
    (tmp / "c.go").write_text("package main\n", encoding="utf-8")
    files = {p.name for p in collect_index_paths(tmp, fast=True, fast_roots=["."])}
    # roots="." may not match; use empty prefix via listing relative
    if not files:
        files = {p.name for p in collect_index_paths(tmp, fast=False)}
    # Scoped roots: put files under packages/
    pkg = tmp / "packages"
    pkg.mkdir()
    (pkg / "a.py").write_text("x=1\n", encoding="utf-8")
    (pkg / "b.ts").write_text("const x=1\n", encoding="utf-8")
    (pkg / "c.go").write_text("package main\n", encoding="utf-8")
    scoped = {
        p.name
        for p in collect_index_paths(tmp, fast=True, fast_roots=["packages"])
    }
    s.check("scoped_includes_py", "a.py" in scoped, str(scoped))
    s.check("scoped_includes_ts", "b.ts" in scoped, str(scoped))
    s.check("scoped_includes_go", "c.go" in scoped, str(scoped))


def wave_live(s: Suite, repo: Path) -> None:
    from pipeline.client import EngineClient
    from pipeline.daemon import ensure_daemon, is_running
    from pipeline.mcp_ship_check import run_ship_ladder
    from pipeline.upgrade import daemon_version, installed_version

    ensure_daemon(repo, force_if_hung=True)
    s.check("daemon_running", is_running() is True)
    health = EngineClient(timeout=15).get("/health")
    s.check("health_ok", health.get("ok") is True, str(health)[:200])
    s.check(
        "version_match",
        daemon_version() == installed_version(),
        f"daemon={daemon_version()} installed={installed_version()}",
    )
    s.check("warm_ready", health.get("warm_state") in {"ready", "warming", "warm"}, str(health.get("warm_state")))

    report = run_ship_ladder(repo=repo)
    s.check("ship_ladder_ok", report.get("ok") is True, json.dumps(report.get("errors")))
    checks = report.get("checks") or {}
    for name in ("gate", "map", "pack_context", "expand_context", "status", "workspace", "collect_hot_context"):
        item = checks.get(name) or {}
        s.check(f"ship_{name}", item.get("ok") is True, str(item)[:160])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Also probe live daemon + ship ladder")
    args = parser.parse_args()

    # Clear idle env so defaults are tested first
    for key in (
        "CTX_ENGINE_IDLE_S",
        "CTX_ENGINE_TRANSITION_DEBOUNCE_S",
        "CTX_EMBED_IDLE_DEMOTE_S",
        "CTX_DEBOUNCE_MS",
        "CTX_REWRITE_DEBOUNCE_MS",
    ):
        os.environ.pop(key, None)

    s = Suite()
    print("=== bug bounty: defaults ===")
    try:
        wave_defaults(s)
    except Exception:  # noqa: BLE001
        s.check("defaults_wave", False, traceback.format_exc())

    with tempfile.TemporaryDirectory(prefix="scubiee-bb-") as td:
        home = Path(td) / "home"
        home.mkdir()
        scratch = Path(td) / "src"
        scratch.mkdir()
        print("=== bug bounty: idle policy ===")
        try:
            wave_idle_policy(s, home)
        except Exception:  # noqa: BLE001
            s.check("idle_wave", False, traceback.format_exc())
        print("=== bug bounty: warm hold ===")
        try:
            wave_warm_hold(s, home)
        except Exception:  # noqa: BLE001
            s.check("warm_wave", False, traceback.format_exc())
        print("=== bug bounty: adopt ===")
        try:
            wave_adopt(s, home)
        except Exception:  # noqa: BLE001
            s.check("adopt_wave", False, traceback.format_exc())
        print("=== bug bounty: debounce ===")
        try:
            wave_debounce_timing(s)
        except Exception:  # noqa: BLE001
            s.check("debounce_wave", False, traceback.format_exc())
        print("=== bug bounty: force gate ===")
        try:
            wave_force_gate(s)
        except Exception:  # noqa: BLE001
            s.check("force_wave", False, traceback.format_exc())
        print("=== bug bounty: polyglot roots ===")
        try:
            wave_paths_polyglot(s, scratch)
        except Exception:  # noqa: BLE001
            s.check("paths_wave", False, traceback.format_exc())

    if args.live:
        print("=== bug bounty: live ship ===")
        # Restore real home for live daemon
        os.environ.pop("CTX_HOME", None)
        try:
            wave_live(s, ROOT)
        except Exception:  # noqa: BLE001
            s.check("live_wave", False, traceback.format_exc())

    print()
    print(f"passed={s.passed} failed={len(s.failed)}")
    for item in s.failed:
        print(f"  - {item}")
    return 1 if s.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
