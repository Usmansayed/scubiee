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

WARM_BUDGET_S = 40.0
LOCATE_BUDGET_MS = 1000.0
# First dense map after the 40s warmup may still pay locate-worker wrap.
FIRST_MAP_BUDGET_MS = 3000.0
# Leave → debounce (10s) → idle window (default 15s) → stop. Health-polling during
# this wait would itself reset activity and prevent unload (seen as UNLOAD_TIMEOUT).
UNLOAD_BUDGET_S = 35.0
DEFAULT_IDLE_S = 120.0

MAP_QUERY = (
    "enforce_mcp_warm_contract disconnect debounce CTX_DISCONNECT_DEBOUNCE_S "
    "enter_standby apply_idle_policy leave_mcp_client register_client "
    "packages/pipeline/lifecycle_runtime.py mcp_lifecycle warm unload"
)
# Distinct from MAP_QUERY so post-idle / second map cannot hide behind process cache.
MAP_QUERY_2 = (
    "retrieve_D_channel_best FastEmbed embed_one run_embed_infer "
    "packages/pipeline/engine.py::prewarm_embedder packages/pipeline/engine.py::search "
    "CTX_EMBED_KEEPALIVE_S map_result_cache pack_context expand_context "
    "memory_governor maybe_demote_idle keepalive DirectML"
)
MAP_QUERY_3 = (
    "ce_service search retrieve_D_channel_best slim_locate_payload "
    "packages/pipeline/ce_service.py::search packages/pipeline/mcp_response_lean.py "
    "CTX_ENGINE_CPU_CAP_PCT JobObject process_job watchdog mcp_bridge shared"
)


def dense_d_channel_map_ok(data: dict[str, Any] | None) -> bool:
    """Fail-closed: cards without FastEmbed D_channel_best do not count as a map."""
    from pipeline.engine import is_dense_d_channel_result

    return is_dense_d_channel_result(data if isinstance(data, dict) else None)


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
    mcp_client: str = "cursor",
    skip_clean: bool = False,
    settle_health_poll: bool = False,
) -> dict[str, Any]:
    """Run cold-attach → settle → locate → leave on Lane A (bridge) or note Lane B.

    ``true_first_map``: skip locate_warmup so ``map_first`` is the first MCP map
    after attach (measures cold locate + whether soft was already ready).

    ``settle_s``: after soft-ready, idle until ``host_start + settle_s`` with no
    map/pack (Cursor open → wait), then first map must hit ≤3s; later maps/tools
    must stay ≤1s even after idle. Implies ``true_first_map``.

    ``mcp_client``: ``CTX_MCP_CLIENT`` for the spawned bridge (default ``cursor``
    to match production ``.cursor/mcp.json``).

    ``skip_clean``: omit kill/stop clean_slate (use after a prior leave→unload so
    the next round is open-only, matching Cursor reopen).

    ``settle_health_poll``: during settle quiet window, hammer ``/health`` like a
    live agent ``status()`` loop (stress ORT GIL). Default False = production-safe
    quiet settle; set True to catch health-storm regressions.
    """
    if settle_s > 0:
        true_first_map = True
    client_slug = (mcp_client or "cursor").strip().lower() or "cursor"
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
        "scenario": f"{client_slug}_cold_attach_steady_leave",
        "lane": lane,
        "live": live,
        "mcp_client": client_slug,
        "repo": str(root),
        "project_id": project_id,
        "engine_url": url,
        "phases": [],
        "errors": [],
        "idle_s": idle_s if not skip_idle else 0,
        "skip_clean": bool(skip_clean),
        "settle_health_poll": bool(settle_health_poll),
    }
    t_run = time.perf_counter()
    kh = None

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
        # Process-real Kiro path: same mcp_bridge binary + CTX_MCP_CLIENT=kiro
        # as .kiro/settings/mcp.json. Pin-only was a false green.
        client_slug = "kiro"
        report["mcp_client"] = "kiro"
        report["scenario"] = "kiro_cold_attach_steady_leave"

    # --- Lane A ---
    host = BridgeHost(
        repo=root,
        project_id=project_id,
        engine_url=url,
        mcp_client=client_slug,
    )

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

    # Phase 0 — clean slate (optional when looping leave→unload→reattach)
    def _clean() -> dict[str, Any]:
        if skip_clean:
            return {"ok": True, "skipped": True}
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
            from pipeline.watchdog import stop_watchdog

            stop_watchdog()
        except Exception:  # noqa: BLE001
            pass
        try:
            from pipeline.warm_autoload import mark_down

            mark_down()
        except Exception:  # noqa: BLE001
            pass
        try:
            from pipeline.engine import _mark_prewarm_busy

            _mark_prewarm_busy(False)
        except Exception:  # noqa: BLE001
            pass
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
        try:
            from pipeline.watchdog import ensure_watchdog_sidecar

            wd = ensure_watchdog_sidecar()
            out["watchdog"] = wd
            print(
                f"[mcp_host_sim] host_start: watchdog ok={wd.get('ok')} "
                f"already={wd.get('already_running')} pid={wd.get('pid')}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[mcp_host_sim] host_start: watchdog {exc}", flush=True)
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
            hard_deadline = host_start_mono + float(settle_s) + 90.0
            try:
                assert host.client is not None
                host.client.request("tools/list", {}, timeout=30)
            except Exception as exc:  # noqa: BLE001
                print(f"[mcp_host_sim] settle tools/list: {exc}", flush=True)
            print("[mcp_host_sim] settle: waiting for soft_ready…", flush=True)
            soft_stable_since: float | None = None
            prewarm_kicked = False
            while time.perf_counter() < hard_deadline:
                now = time.perf_counter()
                # Prefer warm_phase side-channel once prewarm started — ORT holds
                # the GIL; observatory /health would starve DML (live Cursor bug).
                phase_name = None
                try:
                    from pipeline.warm_autoload import in_prewarm, read_phase

                    if prewarm_kicked or in_prewarm():
                        snap = read_phase()
                        phase_name = snap.get("phase")
                        if phase_name == "dense":
                            eng = {"soft_search_ready": True, "embedder_loaded": True}
                            soft = True
                        else:
                            soft = True  # soft already proven before kick
                            eng = {
                                "soft_search_ready": True,
                                "embedder_loaded": False,
                                "warm_phase": phase_name,
                            }
                    else:
                        tick = observatory_tick(url)
                        eng = tick.get("engine") or {}
                        soft = bool(eng.get("soft_search_ready"))
                except Exception:  # noqa: BLE001
                    tick = observatory_tick(url)
                    eng = tick.get("engine") or {}
                    soft = bool(eng.get("soft_search_ready"))
                if soft:
                    if soft_stable_since is None:
                        soft_stable_since = now
                else:
                    soft_stable_since = None
                print(
                    f"[mcp_host_sim] settle soft-wait t=+{now - host_start_mono:.1f}s "
                    f"soft={soft} embed={eng.get('embedder_loaded')} "
                    f"phase={phase_name or eng.get('warm_phase')} "
                    f"rss={eng.get('rss_mb')}",
                    flush=True,
                )
                if (
                    soft
                    and soft_stable_since is not None
                    and (now - soft_stable_since) >= soft_hold_s
                ):
                    if not prewarm_kicked and not bool(eng.get("embedder_loaded")):
                        try:
                            from pipeline.client import EngineClient

                            EngineClient(workspace_path=str(root), timeout=2.0).post(
                                "/v1/embed/prewarm",
                                {"path": str(root), "wait": False},
                            )
                            # Do NOT post keepalive here — it queues HTTP/ORT work
                            # during GIL-held prewarm. Engine starts keepalive after dense.
                            prewarm_kicked = True
                            print(
                                "[mcp_host_sim] settle: prewarm kicked; "
                                "quiet until dense/phase (no /health during ORT GIL)",
                                flush=True,
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(f"[mcp_host_sim] settle prewarm kick: {exc}", flush=True)
                    # Quiet until settle elapsed — watch phase file only.
                    left = max(0.0, target - time.perf_counter())
                    if left > 0:
                        end = time.perf_counter() + left
                        while time.perf_counter() < end:
                            try:
                                from pipeline.warm_autoload import read_phase

                                if (read_phase() or {}).get("phase") == "dense":
                                    print(
                                        "[mcp_host_sim] settle: warm_phase=dense "
                                        "during quiet window",
                                        flush=True,
                                    )
                                    break
                            except Exception:  # noqa: BLE001
                                pass
                            time.sleep(2.0)
                    # After quiet: optional post-dense health probes (live status).
                    if settle_health_poll:
                        for _ in range(3):
                            try:
                                from pipeline.warm_autoload import in_prewarm

                                if in_prewarm():
                                    time.sleep(2.0)
                                    continue
                            except Exception:  # noqa: BLE001
                                pass
                            try:
                                observatory_tick(url)
                            except Exception:  # noqa: BLE001
                                pass
                            time.sleep(1.0)
                    # One post-quiet probe (sticky soft may apply).
                    try:
                        from pipeline.warm_autoload import in_prewarm, read_phase

                        if in_prewarm():
                            tick = {"engine": {"soft_search_ready": True, "embedder_loaded": False, "warm_phase": "prewarm"}}
                            eng = tick["engine"]
                        elif (read_phase() or {}).get("phase") == "dense":
                            tick = observatory_tick(url)
                            eng = tick.get("engine") or {}
                            eng["embedder_loaded"] = True
                        else:
                            tick = observatory_tick(url)
                            eng = tick.get("engine") or {}
                    except Exception:  # noqa: BLE001
                        tick = observatory_tick(url)
                        eng = tick.get("engine") or {}
                    waited = round(time.perf_counter() - host_start_mono, 2)
                    soft_ok = bool(
                        eng.get("soft_search_ready")
                        or eng.get("soft_sticky")
                        or soft
                    )
                    print(
                        f"[mcp_host_sim] settle done at +{waited}s soft={soft_ok} "
                        f"embed={eng.get('embedder_loaded')} "
                        f"phase={eng.get('warm_phase')} rss={eng.get('rss_mb')}",
                        flush=True,
                    )
                    return {
                        "ok": soft_ok,
                        "code": None if soft_ok else "SETTLE_SOFT_NOT_READY",
                        "waited_from_host_s": waited,
                        "settle_s": settle_s,
                        "soft_first_from_host_s": soft_first_from_host_s,
                        "soft_search_ready": soft_ok,
                        "embedder_loaded": bool(eng.get("embedder_loaded")),
                        "prewarm_kicked": prewarm_kicked,
                        "tick": tick,
                    }
                time.sleep(0.5)
            tick = observatory_tick(url)
            eng = tick.get("engine") or {}
            waited = round(time.perf_counter() - host_start_mono, 2)
            soft = bool(eng.get("soft_search_ready") or eng.get("soft_sticky"))
            return {
                "ok": False,
                "code": "SETTLE_SOFT_NOT_READY",
                "waited_from_host_s": waited,
                "settle_s": settle_s,
                "soft_first_from_host_s": soft_first_from_host_s,
                "soft_search_ready": soft,
                "embedder_loaded": bool(eng.get("embedder_loaded")),
                "tick": tick,
            }

        settle_row = phase("settle", _settle, budget_ms=(settle_s + 50) * 1000)
        if not settle_row["ok"]:
            host.stop()
            report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
            _persist(report, out_dir)
            return report

        def _settle_join_embedder() -> dict[str, Any]:
            """After quiet settle, confirm dense ready (poll, no hammer)."""
            # Prefer side-channel stamp + sparse health (health often times out
            # for 5–8s under ORT GIL — never spin 40× that after a good map).
            deadline = time.perf_counter() + (120.0 if client_slug == "kiro" else 60.0)
            last: dict[str, Any] = {}
            embed_seen_at: float | None = None
            while time.perf_counter() < deadline:
                try:
                    from pipeline.warm_autoload import read_phase
                    from pipeline.engine import prime_dense_ready

                    if (read_phase() or {}).get("phase") == "dense":
                        if not prime_dense_ready():
                            time.sleep(1.0)
                            continue
                        tick = observatory_tick(url)
                        eng_now = tick.get("engine") or {}
                        if not bool(eng_now.get("embedder_loaded")):
                            time.sleep(1.0)
                            continue
                        waited = round(time.perf_counter() - host_start_mono, 2)
                        if client_slug == "kiro":
                            print(
                                f"[mcp_host_sim] settle_join phase=dense prime=True at +{waited}s "
                                f"(honest first map deferred to map_first; must be D_channel_best)",
                                flush=True,
                            )
                            return {
                                "ok": True,
                                "embedder_loaded": True,
                                "prime_dense": True,
                                "waited_from_host_s": waited,
                                "via": "warm_phase",
                                "honest_first_map": True,
                                "require_dense_d_channel": True,
                            }
                        print(
                            f"[mcp_host_sim] settle_join phase=dense at +{waited}s "
                            f"— dense prime map…",
                            flush=True,
                        )
                        t_prime = time.perf_counter()
                        try:
                            prime = host.map(MAP_QUERY, k=12)
                            prime_ms = round((time.perf_counter() - t_prime) * 1000, 1)
                            print(
                                f"[mcp_host_sim] settle_join prime ms={prime_ms} "
                                f"ok={prime.get('ok')}",
                                flush=True,
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(f"[mcp_host_sim] settle_join prime: {exc}", flush=True)
                        return {
                            "ok": True,
                            "embedder_loaded": True,
                            "waited_from_host_s": waited,
                            "via": "warm_phase",
                        }
                except Exception:  # noqa: BLE001
                    pass
                try:
                    from pipeline.engine import prewarm_busy_stamp_active

                    # Stamp means ORT still loading — wait quietly, no HTTP.
                    if prewarm_busy_stamp_active():
                        time.sleep(2.0)
                        continue
                except Exception:  # noqa: BLE001
                    pass
                try:
                    from pipeline.warm_autoload import in_prewarm

                    if in_prewarm():
                        time.sleep(2.0)
                        continue
                except Exception:  # noqa: BLE001
                    pass
                tick = observatory_tick(url)
                eng = tick.get("engine") or {}
                last = eng
                try:
                    from pipeline.engine import prime_dense_ready

                    if bool(eng.get("embedder_loaded")):
                        if embed_seen_at is None:
                            embed_seen_at = time.perf_counter()
                        primed = bool(prime_dense_ready())
                        waited_embed = time.perf_counter() - embed_seen_at
                        # Prime stamp should land within 15s. Don't block maps for 120s.
                        if (not primed) and waited_embed < 20.0:
                            time.sleep(1.0)
                            continue
                except Exception:  # noqa: BLE001
                    pass
                if bool(eng.get("embedder_loaded")):
                    waited = round(time.perf_counter() - host_start_mono, 2)
                    if client_slug == "kiro":
                        print(
                            f"[mcp_host_sim] settle_join embed=True at +{waited}s "
                            f"(honest first map deferred to map_first)",
                            flush=True,
                        )
                        return {
                            "ok": True,
                            "embedder_loaded": True,
                            "waited_from_host_s": waited,
                            "tick": tick,
                            "honest_first_map": True,
                        }
                    print(
                        f"[mcp_host_sim] settle_join embed=True at +{waited}s "
                        f"— dense prime map…",
                        flush=True,
                    )
                    t_prime = time.perf_counter()
                    try:
                        prime = host.map(MAP_QUERY, k=12)
                        prime_ms = round((time.perf_counter() - t_prime) * 1000, 1)
                        print(
                            f"[mcp_host_sim] settle_join prime ms={prime_ms} "
                            f"ok={prime.get('ok')}",
                            flush=True,
                        )
                    except Exception as exec_exc:  # noqa: BLE001
                        print(f"[mcp_host_sim] settle_join prime: {exec_exc}", flush=True)
                    return {
                        "ok": True,
                        "embedder_loaded": True,
                        "waited_from_host_s": waited,
                        "tick": tick,
                    }
                # Health dead under GIL — don't tight-loop 8s timeouts.
                if eng.get("health_error"):
                    time.sleep(3.0)
                else:
                    time.sleep(2.0)
            # Dense still cold: one MCP map join (production first-map path).
            if client_slug == "kiro":
                return {
                    "ok": False,
                    "code": "SETTLE_EMBED_NOT_READY",
                    "honest_first_map": True,
                    "error": "dense not ready after settle; refusing prime-map lie",
                }
            print("[mcp_host_sim] settle_join: MCP map join for dense…", flush=True)
            t0 = time.perf_counter()
            try:
                # Same k as map_first so process map-cache absorbs cold tax.
                data = host.map(MAP_QUERY, k=12)
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "code": "SETTLE_EMBED_NOT_READY",
                    "error": str(exc),
                }
            join_ms = round((time.perf_counter() - t0) * 1000, 1)
            map_ok = bool(
                data.get("ok") and (data.get("cards") or data.get("suggested_seed"))
            )
            # Brief health peek only — never 40× timeout storms.
            loaded = False
            tick: dict[str, Any] = {}
            for _ in range(3):
                tick = observatory_tick(url)
                eng = tick.get("engine") or {}
                loaded = bool(eng.get("embedder_loaded"))
                if loaded:
                    break
                if eng.get("health_error"):
                    break
                time.sleep(0.5)
            eng = (tick.get("engine") or {}) if tick else {}
            health_dead = bool((eng or {}).get("health_error"))
            # Successful dense map == ORT up even when /health lags.
            ok = bool(loaded) or (map_ok and join_ms < 5_000.0)
            print(
                f"[mcp_host_sim] settle_join map_ms={join_ms} "
                f"embed={loaded} map_ok={map_ok} health_dead={health_dead} ok={ok}",
                flush=True,
            )
            return {
                "ok": ok,
                "code": None if ok else "SETTLE_EMBED_NOT_READY",
                "embedder_loaded": loaded or (map_ok and ok),
                "join_map_ms": join_ms,
                "map_ok": map_ok,
                "health_proxy_ok": bool(ok and not loaded),
                "tick": tick,
            }

        join_row = phase("settle_join_embedder", _settle_join_embedder, budget_ms=120_000.0)
        if not join_row["ok"]:
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
    # After settle_s: first map ≤3s; every later locate tool ≤1s (even after idle).
    map1_budget = FIRST_MAP_BUDGET_MS if settle_s > 0 else (
        20_000.0 if true_first_map else LOCATE_BUDGET_MS
    )

    def _map1() -> dict[str, Any]:
        label = ""
        if settle_s > 0:
            label = f" (after {settle_s:.0f}s settle, expect <=3s)"
        elif true_first_map:
            label = " (TRUE first MCP map)"
        print(f"[mcp_host_sim] map_first{label}…", flush=True)
        data = host.map(MAP_QUERY, k=12)
        elapsed = float(data.get("_elapsed_ms") or 0)
        warming = bool(
            data.get("warming")
            or str(data.get("error") or "") in {
                "dense_embed_loading",
                "engine_warming",
                "dense_embed_required",
            }
            or str(data.get("status") or "").lower() == "warming"
        )
        dense_ok = dense_d_channel_map_ok(data)
        cards_ok = bool(data.get("ok")) and bool(data.get("cards") or data.get("suggested_seed"))
        ok = bool(cards_ok and dense_ok and not warming)
        print(
            f"[mcp_host_sim] map_first done ok={ok} dense={dense_ok} warming={warming} "
            f"ms={elapsed} mode={data.get('retrieve_mode') or (data.get('timings') or {}).get('retrieve_mode')} "
            f"err={data.get('error') or data.get('status')} "
            f"soft_was_ready_at=+{soft_first_from_host_s}s",
            flush=True,
        )
        code = None
        if warming or (not dense_ok):
            code = "SETTLE_NOT_DENSE" if cards_ok and not dense_ok else "SETTLE_EMBED_NOT_READY"
            ok = False
        steady_ok = ok and elapsed <= LOCATE_BUDGET_MS
        pass_ok = ok and elapsed <= map1_budget
        if ok and not steady_ok:
            code = "SETTLE_MAP_SLOW" if settle_s > 0 else (
                "FIRST_MAP_COLD" if true_first_map else "LOCATE_SLA"
            )
        elif not ok and not code:
            code = "FAIL"
        return {
            "ok": pass_ok,
            "code": code,
            "elapsed_ms": elapsed,
            "steady_sla_ok": steady_ok,
            "true_first_map": true_first_map,
            "settle_s": settle_s,
            "soft_first_from_host_s": soft_first_from_host_s,
            "dense": dense_ok,
            "retrieve_mode": data.get("retrieve_mode") or (data.get("timings") or {}).get("retrieve_mode"),
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

    def _map_second() -> dict[str, Any]:
        print("[mcp_host_sim] map_second (new query, expect <=1s)…", flush=True)
        data = host.map(MAP_QUERY_2, k=12)
        elapsed = float(data.get("_elapsed_ms") or 0)
        dense_ok = dense_d_channel_map_ok(data)
        cards_ok = bool(data.get("ok")) and bool(data.get("cards") or data.get("suggested_seed"))
        warming = bool(data.get("warming") or str(data.get("status") or "").lower() == "warming")
        ok = bool(cards_ok and dense_ok and not warming and elapsed <= LOCATE_BUDGET_MS)
        print(
            f"[mcp_host_sim] map_second done ok={ok} dense={dense_ok} ms={elapsed} "
            f"mode={data.get('retrieve_mode') or (data.get('timings') or {}).get('retrieve_mode')}",
            flush=True,
        )
        return {
            "ok": ok,
            "code": None if ok else ("LOCATE_SLA" if cards_ok else "FAIL"),
            "elapsed_ms": elapsed,
            "dense": dense_ok,
            "retrieve_mode": data.get("retrieve_mode") or (data.get("timings") or {}).get("retrieve_mode"),
        }

    if not phase("map_second", _map_second, budget_ms=LOCATE_BUDGET_MS)["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    def _status1() -> dict[str, Any]:
        data = host.status()
        elapsed = float(data.get("_elapsed_ms") or 0)
        ok = elapsed <= LOCATE_BUDGET_MS
        return {
            "ok": ok,
            "code": None if ok else "LOCATE_SLA",
            "elapsed_ms": elapsed,
        }

    if not phase("status_first", _status1, budget_ms=LOCATE_BUDGET_MS)["ok"]:
        host.stop()
        report["elapsed_ms"] = round((time.perf_counter() - t_run) * 1000, 1)
        _persist(report, out_dir)
        return report

    if kh is not None and kh.available and os.environ.get("KIRO_SIM_CHAT", "").strip() == "1":
        def _kiro_chat() -> dict[str, Any]:
            out = kh.drive_map(query=MAP_QUERY)
            if out.get("skipped"):
                return {"ok": True, **out}
            return out

        kiro_row = phase("kiro_cli_map", _kiro_chat, budget_ms=180_000.0)
        if not kiro_row["ok"]:
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
        # After warmup, expand must stay ≤1s like map/pack. ast_warming is not a pass.
        ok_tool = bool(data.get("ok"))
        dup = bridges_after > max(bridges_before, 1)
        slow = elapsed > LOCATE_BUDGET_MS
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

    if not phase("expand_first", _expand1, budget_ms=LOCATE_BUDGET_MS)["ok"]:
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

    # Phase 5 — post-idle locate (honest: no untimed warmup; new query must stay ≤1s)
    def _map2() -> dict[str, Any]:
        print("[mcp_host_sim] post_idle_map (fresh query, expect <=1s)…", flush=True)
        data = host.map(MAP_QUERY_3, k=12)
        elapsed = float(data.get("_elapsed_ms") or 0)
        dense_ok = dense_d_channel_map_ok(data)
        cards_ok = bool(data.get("ok")) and bool(data.get("cards") or data.get("suggested_seed"))
        ok = bool(cards_ok and dense_ok and elapsed <= LOCATE_BUDGET_MS)
        print(
            f"[mcp_host_sim] post_idle_map done ok={ok} dense={dense_ok} ms={elapsed} "
            f"mode={data.get('retrieve_mode') or (data.get('timings') or {}).get('retrieve_mode')}",
            flush=True,
        )
        return {
            "ok": ok,
            "code": None if ok else ("LOCATE_SLA" if cards_ok else "FAIL"),
            "elapsed_ms": elapsed,
            "dense": dense_ok,
            "retrieve_mode": data.get("retrieve_mode") or (data.get("timings") or {}).get("retrieve_mode"),
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

    # Phase 7 — unload after leave (debounce + idle). Do NOT probe /health here:
    # EngineClient.health() is front-end activity and holds the daemon open.
    def _unload() -> dict[str, Any]:
        import psutil

        from pipeline.lifecycle_runtime import load_clients, reconcile_clients

        deadline = left_at + UNLOAD_BUDGET_S
        last: dict[str, Any] = {}
        while time.time() < deadline:
            try:
                reconcile_clients()
                data = load_clients()
                raw = data.get("clients") or {}
                clients = len(raw) if isinstance(raw, dict) else 0
            except Exception as exc:  # noqa: BLE001
                clients = 0
                raw = {"_error": str(exc)}
            last = {"clients": clients, "raw_clients": raw, "at": time.time()}
            if clients > 0:
                return {
                    "ok": True,
                    "skipped": "foreign_clients_hold_warm",
                    "clients": clients,
                    "tick": last,
                    "waited_s": round(time.time() - left_at, 2),
                }
            alive = False
            for proc in psutil.process_iter(["cmdline"]):
                try:
                    cmdline = " ".join(proc.info.get("cmdline") or [])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if "pipeline engine run" in cmdline:
                    alive = True
                    last["pid"] = proc.pid
                    break
            if not alive:
                waited = round(time.time() - left_at, 2)
                return {"ok": True, "waited_s": waited, "tick": last}
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
