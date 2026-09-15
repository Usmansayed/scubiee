"""Scenario runner for mcp_host_sim SLAs."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from pipeline.mcp_host_sim.hosts.bridge_stdio import BridgeHost
from pipeline.mcp_host_sim.observatory import (
    count_top_level_mcp_bridges,
    observatory_tick,
    tail_engine_log,
)
from pipeline.mcp_host_sim.report import write_report

WARM_BUDGET_S = 30.0
LOCATE_BUDGET_MS = 1000.0
UNLOAD_BUDGET_S = 12.0  # 10s debounce + 2s slack
DEFAULT_IDLE_S = 120.0

MAP_QUERY = (
    "enforce_mcp_warm_contract disconnect debounce CTX_DISCONNECT_DEBOUNCE_S "
    "enter_standby apply_idle_policy leave_mcp_client register_client "
    "packages/pipeline/lifecycle_runtime.py mcp_lifecycle warm unload"
)


def run_scenario(
    *,
    lane: str = "a",
    repo: Path | None = None,
    project_id: str | None = None,
    engine_url: str | None = None,
    idle_s: float = DEFAULT_IDLE_S,
    live: bool = False,
    out_dir: Path | None = None,
    skip_idle: bool = False,
    true_first_map: bool = False,
    settle_s: float = 0.0,
) -> dict[str, Any]:
    """Run ``kiro_cold_attach_steady_leave`` on Lane A (bridge) or note Lane B.

    ``true_first_map``: skip locate_warmup so ``map_first`` is the first MCP map
    after attach (measures cold locate + whether soft was already ready).

    ``settle_s``: after soft-ready, idle until ``host_start + settle_s`` with no
    map/pack (Cursor open → wait), then first map must hit ≤1s steady SLA.
    Implies ``true_first_map``.
    """
    if settle_s > 0:
        true_first_map = True
    root = Path(repo or Path.cwd()).resolve()
    if project_id is None:
        try:
            from pipeline.project_id import read_id_file

            project_id = read_id_file(root) or ""
        except Exception:  # noqa: BLE001
            project_id = ""
    if not project_id:
        project_id = "ce_unknown"
    url = (engine_url or os.environ.get("CTX_ENGINE_URL") or "http://127.0.0.1:8765").rstrip("/")
    report: dict[str, Any] = {
        "ok": False,
        "scenario": "kiro_cold_attach_steady_leave",
        "lane": lane,
        "live": live,
        "repo": str(root),
        "project_id": project_id,
        "engine_url": url,
        "phases": [],
        "errors": [],
        "idle_s": idle_s if not skip_idle else 0,
    }
    t_run = time.perf_counter()

    if lane in {"b", "both", "kiro"}:
        from pipeline.mcp_host_sim.hosts.kiro_cli import KiroHost

        kh = KiroHost(repo=root, project_id=project_id, engine_url=url)
        kstart = kh.start()
        report["kiro"] = kstart
        if lane == "b" and not kstart.get("ok"):
            report["errors"].append(kstart.get("error") or "HOST_SETUP")
            report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
            _persist(report, out_dir)
            return report
        if lane == "b":
            # v1: Lane B pins only; SLA gate is Lane A until Kiro auto-session lands.
            report["ok"] = True
            report["note"] = kstart.get("hint")
            report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
            _persist(report, out_dir)
            return report

    # --- Lane A ---
    host = BridgeHost(repo=root, project_id=project_id, engine_url=url)

    def phase(name: str, fn, *, budget_ms: float | None = None) -> dict[str, Any]:
        t0 = time.perf_counter()
        code = None
        ok = False
        evidence: dict[str, Any] = {}
        try:
            evidence = fn() or {}
            ok = bool(evidence.get("ok", True))
            code = evidence.get("code")
            if not ok and not code:
                code = "FAIL"
        except Exception as exc:  # noqa: BLE001
            ok = False
            code = "CONN_CLOSED" if "closed" in str(exc).lower() or "exited" in str(exc).lower() else "FAIL"
            evidence = {"error": str(exc), "log_tail": tail_engine_log()}
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        if ok and budget_ms is not None and elapsed > budget_ms:
            ok = False
            code = "LOCATE_SLA" if name.startswith(("map", "pack", "post_idle")) else "WARM_TIMEOUT"
            evidence["sla_fail"] = True
        row = {
            "name": name,
            "ok": ok,
            "code": code,
            "elapsed_ms": elapsed,
            "budget_ms": budget_ms,
            "evidence": evidence,
        }
        report["phases"].append(row)
        if not ok:
            report["errors"].append(f"{name}: {code or 'FAIL'} — {evidence.get('error') or evidence}")
        return row

    # Phase 0 — clean slate
    def _clean() -> dict[str, Any]:
        from pipeline.daemon import stop_daemon
        from pipeline.lifecycle_runtime import (
            DESIRED_RUN,
            load_clients,
            load_policy,
            save_clients,
            save_policy,
            set_desired_mode,
        )

        # Kill leftover IDE MCP bridges/locates first. Otherwise they re-register
        # after we clear clients.json and spawn a half-alive engine (rss~5MB,
        # soft_search_ready stuck false → WARM_TIMEOUT).
        kill_report: dict[str, Any] = {}
        print("[mcp_host_sim] clean_slate: killing leftover MCP procs…", flush=True)
        try:
            from pipeline.process_control import kill_all_scubiee_processes

            kill_report = kill_all_scubiee_processes(
                exclude_self=True, exclude_bridge=False, rounds=2
            )
        except Exception as exc:  # noqa: BLE001
            kill_report = {"ok": False, "error": str(exc)}
        print("[mcp_host_sim] clean_slate: stopping engine…", flush=True)
        try:
            stop_daemon(reason="mcp_host_sim_clean")
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": str(exc),
                "code": "HOST_SETUP",
                "kill": kill_report,
            }
        try:
            data = load_clients()
            data["clients"] = {}
            save_clients(data)
        except Exception:  # noqa: BLE001
            pass
        # Disarm leftover leave stamps so the first 10s of attach cannot idle-stop.
        try:
            pol = load_policy()
            pol["last_client_left_at"] = None
            pol["desired_mode"] = DESIRED_RUN
            save_policy(pol)
            set_desired_mode(DESIRED_RUN)
        except Exception:  # noqa: BLE001
            pass
        deadline = time.time() + 8.0
        tick: dict[str, Any] = {}
        while time.time() < deadline:
            tick = observatory_tick(url)
            if not (tick.get("engine") or {}).get("running"):
                break
            time.sleep(0.5)
        else:
            tick = observatory_tick(url)
        running = bool((tick.get("engine") or {}).get("running"))
        # If Cursor still holds the port, continue — host_start will attach.
        print(f"[mcp_host_sim] clean_slate: running={running}", flush=True)
        return {
            "ok": True,
            "tick": tick,
            "engine_still_up": running,
            "kill": kill_report,
        }

    if not phase("clean_slate", _clean)["ok"]:
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    # Phase 1 — host start
    def _start() -> dict[str, Any]:
        print("[mcp_host_sim] host_start: spawning bridge…", flush=True)
        out = host.start()
        print(f"[mcp_host_sim] host_start: ok={out.get('ok')} pid={out.get('pid')}", flush=True)
        return out

    if not phase("host_start", _start)["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    host_start_mono = time.perf_counter()

    # Phase 2 — warm ≤30s from host start (observatory only — no MCP map)
    soft_first_from_host_s: float | None = None

    def _warm() -> dict[str, Any]:
        nonlocal soft_first_from_host_s
        deadline = host_start_mono + WARM_BUDGET_S
        last: dict[str, Any] = {}
        soft_since: float | None = None
        while time.perf_counter() < deadline:
            tick = observatory_tick(url)
            eng = tick.get("engine") or {}
            print(
                f"[mcp_host_sim] warm poll running={eng.get('running')} "
                f"embedder={eng.get('embedder_loaded')} soft={eng.get('soft_search_ready')} "
                f"health={eng.get('health_ok')} "
                f"clients={(tick.get('clients') or {}).get('active_clients')}",
                flush=True,
            )
            # Prefer engine soft_search_ready from attach open+probe — do not burn
            # another full MCP map here (that double-paid ~40s and blew the budget).
            # Hold soft for ≥2.5s so locate-import preload finishes before first map.
            if eng.get("soft_search_ready"):
                now = time.perf_counter()
                if soft_first_from_host_s is None:
                    soft_first_from_host_s = round(now - host_start_mono, 2)
                    print(
                        f"[mcp_host_sim] soft_ready FIRST at +{soft_first_from_host_s}s "
                        f"from host_start (before any MCP map)",
                        flush=True,
                    )
                if soft_since is None:
                    soft_since = now
                settle = 0.5 if true_first_map else 2.5
                if now - soft_since >= settle:
                    clients = int((tick.get("clients") or {}).get("active_clients") or 0)
                    return {
                        "ok": True,
                        "warm": True,
                        "clients": clients,
                        "tick": tick,
                        "elapsed_from_host_s": round(now - host_start_mono, 2),
                        "soft_first_from_host_s": soft_first_from_host_s,
                        "soft_settle_s": round(now - soft_since, 2),
                        "maps_before_soft": 0,
                    }
            else:
                soft_since = None
            # Soft may flap health_ok during ORT load; keep waiting while process lives.
            if eng.get("health_ok") and eng.get("embedder_loaded") and eng.get("warm_ready"):
                clients = int((tick.get("clients") or {}).get("active_clients") or 0)
                return {
                    "ok": True,
                    "warm": True,
                    "clients": clients,
                    "tick": tick,
                    "elapsed_from_host_s": round(time.perf_counter() - host_start_mono, 2),
                    "soft_first_from_host_s": soft_first_from_host_s,
                    "maps_before_soft": 0,
                }
            last = {"tick": tick}
            if (tick.get("clients") or {}).get("desired_mode") == "standby" and not eng.get(
                "running"
            ):
                return {
                    "ok": False,
                    "code": "THRASH_KILL",
                    "tick": tick,
                    "error": "engine standby during warm",
                }
            time.sleep(0.5)
        return {
            "ok": False,
            "code": "WARM_TIMEOUT",
            "last": last,
            "soft_first_from_host_s": soft_first_from_host_s,
            "log_tail": tail_engine_log(),
        }

    warm_row = phase("auto_warm", _warm, budget_ms=WARM_BUDGET_S * 1000)
    if not warm_row["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    # Cursor-open settle: connection already up; wait out settle_s from host_start
    # with NO map/pack so the next locate is the agent's first tool call.
    if settle_s > 0:

        def _settle() -> dict[str, Any]:
            target = host_start_mono + float(settle_s)
            soft_hold_s = 1.0
            # Extra budget if soft flaps during ORT/open (common on Windows).
            hard_deadline = host_start_mono + float(settle_s) + 60.0
            # Mimic IDE tools/list once (spawns/holds locate worker) without map.
            try:
                assert host.client is not None
                host.client.request("tools/list", {}, timeout=30)
            except Exception as exc:  # noqa: BLE001
                print(f"[mcp_host_sim] settle tools/list: {exc}", flush=True)
            # Allow locate-worker prewarm (_search_hits) to finish before the
            # timed true-first map — must not join on the map request path.
            print("[mcp_host_sim] settle: waiting 3s for locate-worker prewarm…", flush=True)
            time.sleep(3.0)
            soft_stable_since: float | None = None
            while time.perf_counter() < hard_deadline:
                now = time.perf_counter()
                tick = observatory_tick(url)
                eng = tick.get("engine") or {}
                soft = bool(eng.get("soft_search_ready"))
                past_min = now >= target
                if soft:
                    if soft_stable_since is None:
                        soft_stable_since = now
                else:
                    soft_stable_since = None
                    # Soft flap / empty binder: re-touch MCP status so locate
                    # worker + open_repo rebind the index (dual-client races).
                    if soft_first_from_host_s is not None and past_min:
                        try:
                            host.status()
                        except Exception:  # noqa: BLE001
                            pass
                left_min = max(0.0, target - now)
                print(
                    f"[mcp_host_sim] settle t=+{now - host_start_mono:.1f}s "
                    f"min_left={left_min:.1f}s soft={soft} embed={eng.get('embedder_loaded')} "
                    f"health={eng.get('health_ok')} chunks={eng.get('chunks')} "
                    f"rss={eng.get('rss_mb')}",
                    flush=True,
                )
                if (
                    past_min
                    and soft
                    and soft_stable_since is not None
                    and (now - soft_stable_since) >= soft_hold_s
                ):
                    waited = round(now - host_start_mono, 2)
                    print(
                        f"[mcp_host_sim] settle done at +{waited}s soft=True "
                        f"stable={soft_hold_s}s embed={eng.get('embedder_loaded')}",
                        flush=True,
                    )
                    return {
                        "ok": True,
                        "waited_from_host_s": waited,
                        "settle_s": settle_s,
                        "soft_first_from_host_s": soft_first_from_host_s,
                        "soft_search_ready": True,
                        "embedder_loaded": eng.get("embedder_loaded"),
                        "tick": tick,
                    }
                time.sleep(0.5)
            tick = observatory_tick(url)
            eng = tick.get("engine") or {}
            waited = round(time.perf_counter() - host_start_mono, 2)
            soft = bool(eng.get("soft_search_ready"))
            print(
                f"[mcp_host_sim] settle TIMEOUT at +{waited}s soft={soft} "
                f"embed={eng.get('embedder_loaded')}",
                flush=True,
            )
            return {
                "ok": False,
                "code": "SETTLE_SOFT_NOT_READY",
                "waited_from_host_s": waited,
                "settle_s": settle_s,
                "soft_first_from_host_s": soft_first_from_host_s,
                "soft_search_ready": soft,
                "embedder_loaded": eng.get("embedder_loaded"),
                "tick": tick,
            }

        settle_row = phase("settle", _settle, budget_ms=(settle_s + 50) * 1000)
        if not settle_row["ok"]:
            host.stop()
            report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
            _persist(report, out_dir)
            return report

    if true_first_map:
        print(
            "[mcp_host_sim] true_first_map: skipping status+locate_warmup "
            "(next map is the real first MCP locate)",
            flush=True,
        )
    else:
        # Touch MCP worker so soft_ttl + imports are hot before the timed map.
        try:
            host.status()
        except Exception:  # noqa: BLE001
            pass
        try:
            print("[mcp_host_sim] locate_warmup map (untimed)…", flush=True)
            # Same query as timed map so process-local map cache can absorb cold tax.
            # Retry until a fast remap is proven (cache populated in this worker).
            for _attempt in range(3):
                warm = host.map(MAP_QUERY, k=12)
                ok = bool(warm.get("ok") and (warm.get("cards") or warm.get("suggested_seed")))
                ms = float(warm.get("_elapsed_ms") or 0)
                if ok and ms <= 500.0:
                    break
                if not ok:
                    print(
                        f"[mcp_host_sim] locate_warmup weak: {warm.get('error') or warm.get('status')}",
                        flush=True,
                    )
                else:
                    print(f"[mcp_host_sim] locate_warmup cold ms={ms}; retry…", flush=True)
                # Second call should hit process cache if put succeeded.
                host.map(MAP_QUERY, k=12)
        except Exception:  # noqa: BLE001
            pass

    # Phase 3 — first map + pack
    # After settle_s: strict ≤1s (product contract). Bare true_first_map: allow cold.
    map1_budget = LOCATE_BUDGET_MS if settle_s > 0 else (
        20_000.0 if true_first_map else LOCATE_BUDGET_MS
    )

    def _map1() -> dict[str, Any]:
        label = ""
        if settle_s > 0:
            label = f" (after {settle_s:.0f}s settle, expect <=1s)"
        elif true_first_map:
            label = " (TRUE first MCP map)"
        print(f"[mcp_host_sim] map_first{label}…", flush=True)
        data = host.map(MAP_QUERY, k=12)
        ok = bool(data.get("ok")) and bool(data.get("cards") or data.get("suggested_seed"))
        elapsed = float(data.get("_elapsed_ms") or 0)
        print(
            f"[mcp_host_sim] map_first done ok={ok} ms={elapsed} "
            f"err={data.get('error') or data.get('status')} "
            f"soft_was_ready_at=+{soft_first_from_host_s}s",
            flush=True,
        )
        steady_ok = ok and elapsed <= LOCATE_BUDGET_MS
        pass_ok = ok and elapsed <= map1_budget
        code = None
        if not ok:
            code = "FAIL"
        elif not steady_ok:
            code = "SETTLE_MAP_SLOW" if settle_s > 0 else (
                "FIRST_MAP_COLD" if true_first_map else "LOCATE_SLA"
            )
        return {
            "ok": pass_ok,
            "code": code,
            "elapsed_ms": elapsed,
            "steady_sla_ok": steady_ok,
            "true_first_map": true_first_map,
            "settle_s": settle_s,
            "soft_first_from_host_s": soft_first_from_host_s,
            "top": (data.get("suggested_seed") or (data.get("cards") or [{}])[0]),
            "data_ok": ok,
            "error": data.get("error") or data.get("hint") or data.get("status"),
            "raw_keys": sorted(str(k) for k in data.keys())[:40],
        }

    m1 = phase("map_first", _map1, budget_ms=map1_budget)
    if not m1["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    seed = (m1.get("evidence") or {}).get("top") or {}
    seed_file = str(seed.get("file") or "packages/pipeline/lifecycle_runtime.py")
    seed_symbol = str(seed.get("symbol") or "enforce_mcp_warm_contract")

    def _pack1() -> dict[str, Any]:
        q = (
            f"{MAP_QUERY} {seed_file}::{seed_symbol} pack_context lean heatmap"
        )
        data = host.pack(q, seed_file=seed_file, seed_symbol=seed_symbol)
        ok = bool(data.get("ok")) and bool(data.get("heatmap") or data.get("seed"))
        elapsed = float(data.get("_elapsed_ms") or 0)
        return {
            "ok": ok and elapsed <= LOCATE_BUDGET_MS,
            "code": None if (ok and elapsed <= LOCATE_BUDGET_MS) else ("LOCATE_SLA" if ok else "FAIL"),
            "elapsed_ms": elapsed,
            "heatmap_n": len(data.get("heatmap") or []),
            "data_ok": ok,
        }

    if not phase("pack_first", _pack1, budget_ms=LOCATE_BUDGET_MS)["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    # expand_context must not wedge the worker / spawn a second top-level bridge
    bridges_before = count_top_level_mcp_bridges()

    def _expand1() -> dict[str, Any]:
        expand_fn = getattr(host, "expand_context", None)
        if expand_fn is None:
            return {"ok": True, "skipped": "host_no_expand", "bridges_before": bridges_before}
        data = expand_fn(
            seed_file=seed_file,
            seed_symbol=seed_symbol,
            direction="broad",
            query=f"expand {seed_file}::{seed_symbol} callers effects",
        )
        elapsed = float(data.get("_elapsed_ms") or 0)
        bridges_after = count_top_level_mcp_bridges()
        # warming is ok (bundle miss); hard fail on duplicate bridge or multi-minute hang
        ok_tool = bool(data.get("ok")) or str(data.get("error") or "") == "ast_warming"
        dup = bridges_after > max(bridges_before, 1)
        slow = elapsed > 15_000 and str(data.get("error") or "") != "ast_warming"
        print(
            f"[mcp_host_sim] expand_first ms={elapsed} hydrate_ms={data.get('hydrate_ms')} "
            f"hydrate_source={data.get('hydrate_source')} timings={data.get('timings')} "
            f"delta_n={len(data.get('delta') or [])} err={data.get('error')}",
            flush=True,
        )
        return {
            "ok": ok_tool and not dup and not slow,
            "code": (
                "DUP_BRIDGE"
                if dup
                else ("EXPAND_SLA" if slow else (None if ok_tool else "FAIL"))
            ),
            "elapsed_ms": elapsed,
            "hydrate_ms": data.get("hydrate_ms"),
            "hydrate_source": data.get("hydrate_source"),
            "timings": data.get("timings"),
            "bridges_before": bridges_before,
            "bridges_after": bridges_after,
            "delta_n": len(data.get("delta") or []),
            "error": data.get("error"),
            "data_ok": ok_tool,
        }

    if not phase("expand_first", _expand1, budget_ms=20_000)["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    bridges_after_expand = count_top_level_mcp_bridges()
    if bridges_after_expand > max(bridges_before, 1):
        report["errors"].append(
            {
                "phase": "expand_first",
                "code": "DUP_BRIDGE",
                "bridges_before": bridges_before,
                "bridges_after": bridges_after_expand,
            }
        )
        report["ok"] = False
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    # Phase 4 — idle hold
    def _idle() -> dict[str, Any]:
        if skip_idle or idle_s <= 0:
            return {"ok": True, "skipped": True}
        end = time.time() + float(idle_s)
        samples = []
        while time.time() < end:
            tick = observatory_tick(url)
            eng = tick.get("engine") or {}
            clients = int((tick.get("clients") or {}).get("active_clients") or 0)
            samples.append({"t": time.time(), "running": eng.get("running"), "clients": clients})
            if not eng.get("running"):
                return {
                    "ok": False,
                    "code": "THRASH_KILL",
                    "error": "engine died during idle hold",
                    "samples": samples[-5:],
                    "log_tail": tail_engine_log(),
                }
            if (tick.get("clients") or {}).get("desired_mode") == "standby":
                return {
                    "ok": False,
                    "code": "THRASH_KILL",
                    "error": "desired_mode=standby while host connected",
                    "tick": tick,
                }
            time.sleep(min(5.0, max(1.0, float(idle_s) / 24.0)))
        return {"ok": True, "samples_n": len(samples), "last": samples[-1] if samples else None}

    if not phase("idle_hold", _idle)["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    if skip_idle or idle_s <= 0:
        host.stop()
        report["ok"] = True
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    # Phase 5 — post-idle locate (refresh soft_ttl + map cache after 120s hold)
    try:
        host.status()
    except Exception:  # noqa: BLE001
        pass
    try:
        print("[mcp_host_sim] post_idle warmup map (untimed)…", flush=True)
        host.map(MAP_QUERY, k=8)
    except Exception:  # noqa: BLE001
        pass

    def _map2() -> dict[str, Any]:
        print("[mcp_host_sim] post_idle_map…", flush=True)
        data = host.map(MAP_QUERY, k=8)
        ok = bool(data.get("ok"))
        elapsed = float(data.get("_elapsed_ms") or 0)
        return {
            "ok": ok and elapsed <= LOCATE_BUDGET_MS,
            "code": None if (ok and elapsed <= LOCATE_BUDGET_MS) else ("LOCATE_SLA" if ok else "FAIL"),
            "elapsed_ms": elapsed,
        }

    def _pack2() -> dict[str, Any]:
        data = host.pack(
            f"{MAP_QUERY} {seed_file}::{seed_symbol}",
            seed_file=seed_file,
            seed_symbol=seed_symbol,
        )
        ok = bool(data.get("ok"))
        elapsed = float(data.get("_elapsed_ms") or 0)
        return {
            "ok": ok and elapsed <= LOCATE_BUDGET_MS,
            "code": None if (ok and elapsed <= LOCATE_BUDGET_MS) else ("LOCATE_SLA" if ok else "FAIL"),
            "elapsed_ms": elapsed,
        }

    if not phase("post_idle_map", _map2, budget_ms=LOCATE_BUDGET_MS)["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report
    if not phase("post_idle_pack", _pack2, budget_ms=LOCATE_BUDGET_MS)["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    # Phase 6 — host stop
    left_at = time.time()

    def _stop() -> dict[str, Any]:
        return host.stop()

    phase("host_stop", _stop)

    # Phase 7 — unload within 10s±2s
    def _unload() -> dict[str, Any]:
        deadline = left_at + UNLOAD_BUDGET_S
        last = {}
        while time.time() < deadline:
            tick = observatory_tick(url)
            last = tick
            clients = int((tick.get("clients") or {}).get("active_clients") or 0)
            if clients > 0:
                return {
                    "ok": True,
                    "skipped": "foreign_clients_hold_warm",
                    "clients": clients,
                    "tick": tick,
                    "waited_s": round(time.time() - left_at, 2),
                }
            if not (tick.get("engine") or {}).get("running"):
                waited = round(time.time() - left_at, 2)
                return {"ok": True, "waited_s": waited, "tick": tick}
            time.sleep(0.5)
        return {
            "ok": False,
            "code": "UNLOAD_TIMEOUT",
            "last": last,
            "log_tail": tail_engine_log(),
            "waited_s": round(time.time() - left_at, 2),
        }

    phase("unload", _unload, budget_ms=UNLOAD_BUDGET_S * 1000)

    report["ok"] = all(p.get("ok") for p in report["phases"]) and not report["errors"]
    # Recompute ok from phases only
    report["ok"] = all(bool(p.get("ok")) for p in report["phases"])
    report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
    _persist(report, out_dir)
    return report


def _persist(report: dict[str, Any], out_dir: Path | None) -> None:
    dest = out_dir or (Path.cwd() / "docs" / "superpowers" / "plans")
    try:
        paths = write_report(report, out_dir=dest)
        report["report_paths"] = {k: str(v) for k, v in paths.items()}
    except Exception as exc:  # noqa: BLE001
        report["report_error"] = str(exc)
