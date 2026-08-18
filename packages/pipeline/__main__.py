"""CLI: python -m pipeline index|search|status|serve"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

from pipeline.indexer import IndexDeferred, index_repo
from pipeline.searcher import search_repo
from pipeline.store import PipelineStore


def _progress_bar(notice: str):
    from pipeline.progress_ui import InstallProgress

    bar = InstallProgress()
    bar.start(notice)
    return bar


def cmd_index(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    bar = _progress_bar("This may take a few minutes. Indexing the repository.")

    roots = None
    if getattr(args, "roots", None):
        roots = [r.strip() for r in str(args.roots).split(",") if r.strip()]

    fast = bool(getattr(args, "fast", False))
    if roots and not fast:
        # --roots only narrows the fast path. Honouring it literally would mean a
        # full index of every supported extension, which is the opposite of what
        # someone restricting roots is asking for.
        print(
            "[index] --roots implies --fast; indexing .py under "
            f"{', '.join(roots)} only",
            file=sys.stderr,
        )
        fast = True
    args.fast = fast

    # CLI index always registers the project (shared pipeline)
    from pipeline.registration import register_project

    reg = register_project(
        root,
        always_allow=True,
        index=False,  # index via index_repo below for progress hooks
        fast=fast,
    )
    if not reg.ok:
        bar.fail(reg.error if hasattr(reg, "error") else "registration failed")
        print(json.dumps(reg.to_dict(), indent=2))
        return 1

    try:
        stats = index_repo(
            root,
            force=args.force,
            bits=args.bits,
            embed_model=args.model,
            fast=fast,
            fast_roots=roots,
            progress=bar,
        )
    except IndexDeferred as exc:
        bar.fail(str(exc.reason))
        print(
            json.dumps(
                {
                    "ok": False,
                    "deferred": True,
                    "error": str(exc.reason),
                    "pressure": exc.pressure,
                },
                indent=2,
            )
        )
        return 1
    bar.finish("Ready")
    out = stats.__dict__.copy()
    out["project_id"] = reg.project_id
    out["registered"] = True
    print(json.dumps(out, indent=2))
    return 0


def cmd_resources(args: argparse.Namespace) -> int:
    """Show hardware snapshot + live resource pressure / budgets."""
    from pipeline.hardware import ensure_hardware_snapshot, load_hardware, save_hardware
    from pipeline.resources import get_resource_manager, reset_resource_manager_for_tests

    if args.refresh:
        snap = ensure_hardware_snapshot(force=True)
    else:
        snap = load_hardware() or ensure_hardware_snapshot(force=False)
    if args.save:
        save_hardware(snap)

    if args.reset_rm:
        reset_resource_manager_for_tests()

    rm = get_resource_manager()
    status = rm.status()
    print(
        json.dumps(
            {
                "hardware": {
                    "os": snap.get("os"),
                    "cpu_model": snap.get("cpu_model"),
                    "cpu_count": snap.get("cpu_count_logical") or snap.get("cpu_count"),
                    "ram_total_gb": round((snap.get("ram_total_bytes") or 0) / 1e9, 2)
                    if snap.get("ram_total_bytes")
                    else None,
                    "recommended_accel": snap.get("recommended_accel"),
                    "libraries": snap.get("libraries"),
                },
                "resources": status,
            },
            indent=2,
            default=str,
        )
    )
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    """Run a named CE verification tier and emit a JSON report."""
    from pipeline.test_runner import build_test_plan, run_plan

    root = Path(args.path).resolve()
    plan = build_test_plan(args.tier, root=root)
    report = run_plan(
        plan,
        root=root,
        external_client_available=bool(getattr(args, "clients", False)),
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


def cmd_preflight(args: argparse.Namespace) -> int:
    from pipeline.preflight import inspect_capabilities

    report = inspect_capabilities(require_semantic=not bool(args.lexical_only))
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("ok") else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    from pipeline.doctor import (
        apply_safe_repairs,
        apply_safe_repairs_all,
        doctor_all,
        doctor_repo,
    )

    root = Path(args.path).resolve()
    if args.fix and args.all:
        out = apply_safe_repairs_all()
    elif args.fix:
        out = apply_safe_repairs(root)
    elif args.all:
        out = doctor_all()
    else:
        out = doctor_repo(root)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


def cmd_certify(args: argparse.Namespace) -> int:
    from pipeline.certify import certify

    out = certify(
        Path(args.path).resolve(),
        skip_daemon=bool(args.skip_daemon),
        skip_canary=not bool(args.canary),
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


def cmd_register(args: argparse.Namespace) -> int:
    from pipeline.registration import register_project

    root = Path(args.path).resolve()
    result = register_project(
        root,
        always_allow=bool(args.always_allow),
        index=not bool(args.no_index),
        fast=bool(args.fast),
        force_reindex=bool(args.force),
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


def cmd_repo_lifecycle(args: argparse.Namespace) -> int:
    from pipeline.repo_lifecycle import (
        activate_repo,
        initialize_repo,
        list_managed_repos,
        never_index_repo,
        pause_repo,
        rebuild_repo,
        remove_repo,
        resume_repo,
        sync_now_repo,
    )

    action = args.command
    if action == "list":
        out: dict | list = list_managed_repos()
    else:
        root = Path(args.path).resolve()
        if action == "initialize":
            out = initialize_repo(
                root,
                index=not bool(args.no_index),
                always_allow=not bool(args.allow_once),
            )
        elif action == "activate":
            out = activate_repo(root)
        elif action == "pause":
            out = pause_repo(root, reason=args.reason)
        elif action == "resume":
            out = resume_repo(root)
        elif action == "sync-now":
            out = sync_now_repo(root)
        elif action == "rebuild":
            out = rebuild_repo(root)
        elif action == "remove":
            out = remove_repo(root, delete_store=bool(args.delete_store))
        elif action == "never-index":
            out = never_index_repo(root, reason=args.reason)
        else:
            out = {"ok": False, "error": f"unknown lifecycle action: {action}"}
    print(json.dumps(out, indent=2, default=str))
    return 0 if isinstance(out, list) or out.get("ok") else 1


def cmd_settings(args: argparse.Namespace) -> int:
    from pipeline.settings import (
        get_registration_mode,
        load_prefs,
        prefs_path,
        save_prefs,
        set_registration_mode,
    )

    if args.show or (not args.mode and args.incremental is None and args.watching is None):
        prefs = load_prefs()
        prefs["prefs_path"] = str(prefs_path())
        print(json.dumps(prefs, indent=2))
        return 0

    prefs = load_prefs()
    if args.mode:
        set_registration_mode(args.mode)
        prefs = load_prefs()
    if args.incremental is not None:
        prefs["incremental_indexing"] = bool(args.incremental)
    if args.watching is not None:
        prefs["file_watching"] = bool(args.watching)
    save_prefs(prefs)
    print(json.dumps(load_prefs(), indent=2))
    print(
        f"[settings] registration_mode={get_registration_mode()} "
        f"(dashboard: python -m pipeline dashboard)",
        file=sys.stderr,
    )
    return 0


def interpret_search_cli(first: str, second: str | None) -> tuple[Path, str]:
    """Accept both `search QUERY [PATH]` and the common `search PATH QUERY` mix-up.

    A directory as the first positional is treated as the repo; otherwise the
    first token is the query and the second (default `.`) is the repo.
    """
    second = second if second not in (None, "") else "."
    first_path = Path(first)
    second_path = Path(second)
    first_is_dir = first in {".", ".."} or first_path.is_dir()
    second_is_dir = second in {".", ".."} or second_path.is_dir()
    if first_is_dir and not second_is_dir:
        return first_path.resolve(), second
    return second_path.resolve(), first


def cmd_search(args: argparse.Namespace) -> int:
    root, query = interpret_search_cli(args.query, args.path)
    if not root.is_dir():
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"not a directory: {root}",
                    "hint": "Usage: ctx search \"query\"  or  ctx search . \"query\"",
                }
            ),
            file=sys.stderr,
        )
        return 1
    t0 = time.perf_counter()
    try:
        hits = search_repo(
            root,
            query,
            top_k=args.top_k,
            use_server=not args.local,
            server_url=args.url if not args.local else None,
        )
    except Exception as exc:
        from pipeline.searcher import SearchEngineError

        if isinstance(exc, SearchEngineError):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(exc),
                        "hint": exc.hint,
                        "mode": "daemon",
                    },
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
        raise
    ms = (time.perf_counter() - t0) * 1000
    print(
        json.dumps(
            {
                "latency_ms": round(ms, 1),
                "hits": [
                    {
                        "rank": h.rank,
                        "file": h.file,
                        "score": h.score,
                        "chunk_id": h.chunk_id,
                        "preview": h.preview,
                        "source": h.source,
                    }
                    for h in hits
                ],
            },
            indent=2,
        )
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    store = PipelineStore(root)
    meta = store.load_meta()
    col = store.get_collection()
    from pipeline.freshness import check_freshness
    from pipeline.vectordb import VectorDatabase

    freshness = check_freshness(
        root,
        store.load_merkle(),
        indexed_head=meta.get("git_head"),
        file_mtimes=store.load_mtimes(),
    ).to_dict()
    vdb = VectorDatabase()
    warm = None
    try:
        with urllib.request.urlopen(
            (args.url or "http://127.0.0.1:8765").rstrip("/") + "/health", timeout=2
        ) as resp:
            warm = json.loads(resp.read().decode("utf-8"))
    except Exception:
        warm = {"ok": False, "warm": False}

    print(
        json.dumps(
            {
                "root": str(root),
                "store": str(store.base),
                "collection": store.collection_name,
                "meta": meta,
                "chunks": len(store.load_chunks()),
                "vectors": col.stats() if col else None,
                "merkle_files": len(store.load_merkle()),
                "freshness": freshness,
                "vectordb": {
                    "root": str(vdb.root),
                    "collections": vdb.list_collections(),
                },
                "server": warm,
            },
            indent=2,
        )
    )
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    from pipeline.incremental import incremental_sync

    root = Path(args.path).resolve()
    result = incremental_sync(root)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.error is None else 1


def cmd_serve(args: argparse.Namespace) -> int:
    """Alias for Context Engine daemon (foreground)."""
    from pipeline.server import run_server

    run_server(Path(args.path).resolve(), host=args.host, port=args.port)
    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Start, inspect, or stop the dedicated localhost operator dashboard."""
    from pipeline.dashboard_server import (
        dashboard_status,
        start_dashboard,
        stop_dashboard,
    )

    if args.action == "stop":
        out = stop_dashboard()
    elif args.status:
        out = dashboard_status()
    else:
        out = start_dashboard(open_browser=not args.no_open)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


def cmd_engine(args: argparse.Namespace) -> int:
    """Context Engine daemon control: start | stop | status | run | ensure | watchdog."""
    from pipeline.client import EngineClient, engine_url
    from pipeline.daemon import ensure_daemon, is_running, start_daemon, stop_daemon
    from pipeline.lifecycle_runtime import (
        DESIRED_STANDBY,
        register_logon_autostart,
        run_supervisor,
        set_desired_mode,
        unregister_logon_autostart,
    )
    from pipeline.watchdog import (
        start_watchdog,
        stop_watchdog,
        watchdog_loop,
        watchdog_status,
    )

    action = args.action
    if action == "run":
        from pipeline.server import run_server

        run_server(
            Path(args.path).resolve(),
            host=args.host,
            port=args.port,
            open_on_start=not args.no_open,
        )
        return 0
    if action == "watchdog":
        # Foreground loop for the in-session sidecar child (not the --logon path)
        watchdog_loop()
        return 0
    if action == "supervisor":
        run_supervisor(logon=bool(getattr(args, "logon", False)))
        return 0
    if action == "autostart":
        if getattr(args, "off", False):
            out = unregister_logon_autostart()
        else:
            out = register_logon_autostart()
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("ok") else 1
    if action == "start":
        result = start_daemon(
            Path(args.path).resolve() if args.path else None,
            host=args.host,
            port=args.port,
            wait_s=float(args.wait),
        )
        # Start watchdog if daemon is usable (health may race past wait timeout)
        from pipeline.daemon import is_running as _ir
        from pipeline.lifecycle_runtime import note_activity

        wd: dict
        if result.get("ok") or _ir():
            note_activity()
            wd = start_watchdog()
            result["ok"] = True
        else:
            wd = {"ok": False, "skipped": True}
        out = {**result, "watchdog": wd}
        print(json.dumps(out, indent=2))
        return 0 if result.get("ok") else 1
    if action == "stop":
        set_desired_mode(DESIRED_STANDBY)
        wd = stop_watchdog()
        eng = stop_daemon()
        print(json.dumps({"ok": True, "watchdog": wd, "engine": eng}, indent=2))
        return 0
    if action == "status":
        client = EngineClient()
        healthy = is_running()
        payload = {
            "url": engine_url(),
            "running": healthy,
            "health": client.get("/health") if healthy else None,
            "watchdog": watchdog_status(),
        }
        if healthy:
            payload["status"] = client.status(str(Path(args.path or ".").resolve()))
        print(json.dumps(payload, indent=2, default=str))
        return 0 if healthy else 1
    if action == "ensure":
        result = ensure_daemon(Path(args.path or ".").resolve())
        if result.get("ok"):
            result["watchdog"] = start_watchdog()
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    print(f"unknown action {action}", file=sys.stderr)
    return 2


def cmd_mcp(args: argparse.Namespace) -> int:
    import os

    if args.path:
        os.environ["CTX_REPO"] = str(Path(args.path).resolve())
    from pipeline.mcp_locate import main as mcp_main

    mcp_main()
    return 0


def _configure_machine(
    args: argparse.Namespace,
    *,
    report: bool = True,
    progress: object | None = None,
) -> int:
    """Once-per-machine accel: detect profile, install, model, calibrate batch."""
    from pipeline.accel import ACCEL_PATH, configure, load_accel

    if getattr(args, "status", False):
        prof = load_accel()
        print(
            json.dumps(
                {
                    "accel_path": str(ACCEL_PATH),
                    "preferred_profile": None if prof is None else prof.__dict__,
                    "envelope": None if prof is None else prof.envelope,
                },
                indent=2,
                default=str,
            )
        )
        return 0

    existing = load_accel()
    if existing is not None and not bool(getattr(args, "repair", False)):
        if progress is not None:
            progress.set(92, "Using saved hardware profile")
        if report:
            print(json.dumps(existing.__dict__, indent=2, default=str))
        return 0

    prof = configure(
        force_profile=getattr(args, "profile", None),
        install_pkgs=not bool(getattr(args, "skip_install", False)),
        download_model=not bool(getattr(args, "skip_model", False)),
        bench=not bool(getattr(args, "skip_bench", False)),
        force_install=bool(getattr(args, "repair", False)),
        progress=progress,
    )
    if report:
        print(json.dumps(prof.__dict__, indent=2, default=str))
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Enroll a repository under Context Engine and index it."""
    from pipeline.accel import load_accel

    if load_accel() is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "machine_not_setup",
                    "repair": "python -m pipeline setup",
                },
                indent=2,
            )
        )
        return 1

    root = Path(getattr(args, "path", ".") or ".").resolve()
    bar = _progress_bar("This may take a few minutes. Indexing the repository.")
    from pipeline.repo_lifecycle import initialize_repo

    try:
        roots = None
        if getattr(args, "roots", None):
            roots = [r.strip() for r in str(args.roots).split(",") if r.strip()]
        fast = bool(getattr(args, "fast", False))
        if roots and not fast:
            fast = True
        out = initialize_repo(
            root,
            index=not bool(getattr(args, "no_index", False)),
            always_allow=not bool(getattr(args, "allow_once", False)),
            progress=bar,
            fast=fast,
            fast_roots=roots,
        )
    except Exception as exc:  # noqa: BLE001
        bar.fail(str(exc))
        raise
    if out.get("ok"):
        try:
            from pipeline.daemon import ensure_daemon

            out["daemon"] = ensure_daemon(root)
        except Exception as exc:  # noqa: BLE001
            out["daemon"] = {"ok": False, "error": str(exc)}
        bar.finish("Ready")
    else:
        bar.fail(str(out.get("error") or "init failed"))
    if not sys.stdout.isatty():
        print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


def cmd_setup(args: argparse.Namespace) -> int:
    """One user-facing install: package config + local service + Cursor MCP."""
    import os

    from pipeline.progress_ui import InstallProgress

    if getattr(args, "status", False):
        return _configure_machine(args)

    bar = InstallProgress()
    bar.start(
        "This may take a few minutes. Downloading and installing the Scubiee engine."
    )
    try:
        bar.set(4, "Checking engine modules")
        try:
            from graphify.extract import extract  # noqa: F401
            from graphify.build import build  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            bar.fail(f"graphify missing/broken: {exc}")
            return 1

        bar.set(10, "Detecting hardware")
        if not args.skip_accel:
            rc = _configure_machine(args, report=False, progress=bar)
            if rc != 0:
                bar.fail("Hardware setup failed")
                return rc
        else:
            try:
                from pipeline.hardware import ensure_hardware_snapshot

                ensure_hardware_snapshot(force=True)
            except Exception as exc:  # noqa: BLE001
                bar.fail(f"hardware snapshot: {exc}")
                return 1

        repo = Path(args.repo or args.index_path or ".").resolve()
        os.environ["CTX_REPO"] = str(repo)
        host = args.host
        port = int(args.port)
        os.environ["CTX_ENGINE_URL"] = f"http://{host}:{port}"

        bar.set(94, "Registering logon supervisor")
        from pipeline.lifecycle_runtime import install_session_runtime

        runtime = install_session_runtime()
        if isinstance(runtime, dict) and runtime.get("ok") is False:
            bar.fail("Could not start the session supervisor")
            return 1

        bar.set(98, "Registering Cursor MCP")
        from pipeline.mcp_install import write_cursor_mcp

        write_cursor_mcp(repo, host=host, port=port)

        if args.index_path or args.register:
            bar.set(99, "Enrolling repository")
            from pipeline.git_family import reconcile_git_families
            from pipeline.repo_lifecycle import initialize_repo

            reconcile_git_families(prefer_root=repo)
            print(
                json.dumps(
                    initialize_repo(repo, index=True, always_allow=True),
                    indent=2,
                    default=str,
                )
            )

        bar.finish("Ready. Next: ctx init <repo>")
        return 0
    except Exception as exc:  # noqa: BLE001
        bar.fail(str(exc))
        return 1


def _write_mcp_config(repo: Path, host: str, port: int) -> None:
    """Minimal MCP write when install_mcp import fails."""
    py = Path(sys.executable).resolve()
    root = Path(__file__).resolve().parents[2]
    entry = {
        "command": str(py).replace("\\", "/"),
        "args": ["-u", "-m", "pipeline.mcp_locate"],
        "env": {
            "PYTHONPATH": str(root / "packages").replace("\\", "/"),
            "CTX_REPO": str(repo).replace("\\", "/"),
            "CTX_ENGINE_URL": f"http://{host}:{port}",
            "CTX_TOKEN_MODE": "savings",
            "CTX_BACKGROUND_SYNC": "1",
            "CTX_ALLOW_BG_FULL": "0",
            "CTX_AUTO_INDEX": "1",
            "CTX_SYNC_INTERVAL_MS": "300000",
            "CTX_REGISTRATION_MODE": "automatic",
            "CTX_MCP_SURFACE": "phase",
            "PYTHONUTF8": "1",
        },
    }
    # Project-scoped only: a user-level entry pins one CTX_REPO for every
    # workspace and shadows the per-project config.
    for path in (Path.cwd() / ".cursor" / "mcp.json",):
        path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {"mcpServers": {}}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        data.setdefault("mcpServers", {})["context-engine"] = entry
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"[setup] wrote {path}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    try:
        from importlib.metadata import version as _pkg_version

        _ver = _pkg_version("scubiee")
    except Exception:  # noqa: BLE001
        _ver = "0.2.5"
    parser = argparse.ArgumentParser(
        prog="pipeline",
        description="Context Engine — Merkle + Graphify + TurboQuant + FAISS + D_rerank",
    )
    parser.add_argument("--version", action="version", version=f"scubiee {_ver}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index", help="Index a repository")
    p_index.add_argument("path", nargs="?", default=".", help="Repo path")
    p_index.add_argument("--force", action="store_true")
    p_index.add_argument(
        "--bits",
        type=int,
        default=8,
        help="TurboQuant bits (default 8; 4 is too lossy for CodeRank quality)",
    )
    p_index.add_argument(
        "--model",
        default="nomic-ai/CodeRankEmbed",
        help="Embedding model (default CodeRankEmbed)",
    )
    p_index.add_argument(
        "--fast",
        action="store_true",
        help="Fast config: .py under CTX_FAST_ROOTS / --roots only",
    )
    p_index.add_argument(
        "--roots",
        default=None,
        help="Comma-separated fast roots (default: src,lib,app,packages,testdata,...)",
    )
    p_index.set_defaults(func=cmd_index)

    p_res = sub.add_parser(
        "resources",
        help="Hardware snapshot + live CPU/RAM pressure and adaptive budgets",
    )
    p_res.add_argument("--refresh", action="store_true", help="Re-detect hardware")
    p_res.add_argument("--save", action="store_true", help="Write hardware.json")
    p_res.add_argument(
        "--reset-rm",
        action="store_true",
        help="Reset in-process ResourceManager singleton",
    )
    p_res.set_defaults(func=cmd_resources)

    p_test = sub.add_parser(
        "test",
        help="Run CE verification tier: quick | core | fault | install | clients | all",
    )
    p_test.add_argument(
        "tier",
        choices=["quick", "core", "fault", "install", "clients", "all"],
        nargs="?",
        default="quick",
    )
    p_test.add_argument("path", nargs="?", default=".", help="Repository root")
    p_test.add_argument(
        "--clients",
        action="store_true",
        help="Permit external-client suites when the required client is installed",
    )
    p_test.set_defaults(func=cmd_test)

    p_pre = sub.add_parser("preflight", help="Check required local CE dependencies")
    p_pre.add_argument("path", nargs="?", default=".")
    p_pre.add_argument(
        "--lexical-only",
        action="store_true",
        help="Do not require semantic embedding backend",
    )
    p_pre.set_defaults(func=cmd_preflight)

    p_doctor = sub.add_parser("doctor", help="Readiness + repair diagnostics")
    p_doctor.add_argument("path", nargs="?", default=".")
    p_doctor.add_argument(
        "--all",
        action="store_true",
        help="Doctor every managed repository",
    )
    p_doctor.add_argument(
        "--fix",
        action="store_true",
        help="Apply safe repairs only (never pip install, rebuild, or Forget)",
    )
    p_doctor.set_defaults(func=cmd_doctor)

    p_cert = sub.add_parser("certify", help="Release certification gate")
    p_cert.add_argument("path", nargs="?", default=".")
    p_cert.add_argument("--skip-daemon", action="store_true")
    p_cert.add_argument("--canary", action="store_true", help="Include warm semantic canary")
    p_cert.set_defaults(func=cmd_certify)

    p_reg = sub.add_parser(
        "register",
        help="Register a project (id + optional index). Same pipeline as MCP consent.",
    )
    p_reg.add_argument("path", nargs="?", default=".")
    p_reg.add_argument(
        "--always-allow",
        action="store_true",
        help="Skip future MCP registration prompts for this project",
    )
    p_reg.add_argument("--no-index", action="store_true", help="Only write id/registry")
    p_reg.add_argument("--fast", action="store_true", help="Fast index roots only")
    p_reg.add_argument("--force", action="store_true", help="Force reindex")
    p_reg.set_defaults(func=cmd_register)

    p_initialize = sub.add_parser(
        "initialize",
        help="Initialize a managed repository and reconcile an existing index",
    )
    p_initialize.add_argument("path", nargs="?", default=".")
    p_initialize.add_argument("--no-index", action="store_true")
    p_initialize.add_argument(
        "--allow-once",
        action="store_true",
        help="Do not persist always-allow registration consent",
    )
    p_initialize.set_defaults(func=cmd_repo_lifecycle, command="initialize")

    p_activate = sub.add_parser("activate", help="Activate a managed repository")
    p_activate.add_argument("path", nargs="?", default=".")
    p_activate.set_defaults(func=cmd_repo_lifecycle, command="activate")

    p_pause = sub.add_parser("pause", help="Pause repository background indexing")
    p_pause.add_argument("path", nargs="?", default=".")
    p_pause.add_argument("--reason", default=None)
    p_pause.set_defaults(func=cmd_repo_lifecycle, command="pause")

    p_resume = sub.add_parser("resume", help="Resume repository background indexing")
    p_resume.add_argument("path", nargs="?", default=".")
    p_resume.set_defaults(func=cmd_repo_lifecycle, command="resume")

    p_sync_now = sub.add_parser("sync-now", help="Reconcile repository freshness now")
    p_sync_now.add_argument("path", nargs="?", default=".")
    p_sync_now.set_defaults(func=cmd_repo_lifecycle, command="sync-now")

    p_rebuild = sub.add_parser("rebuild", help="Force a full repository index rebuild")
    p_rebuild.add_argument("path", nargs="?", default=".")
    p_rebuild.set_defaults(func=cmd_repo_lifecycle, command="rebuild")

    p_remove = sub.add_parser("remove", help="Remove repository lifecycle management")
    p_remove.add_argument("path", nargs="?", default=".")
    p_remove.add_argument(
        "--delete-store",
        action="store_true",
        help="Also delete the repository index store",
    )
    p_remove.set_defaults(func=cmd_repo_lifecycle, command="remove")

    p_never = sub.add_parser("never-index", help="Persistently deny indexing for a repository")
    p_never.add_argument("path", nargs="?", default=".")
    p_never.add_argument("--reason", default=None)
    p_never.set_defaults(func=cmd_repo_lifecycle, command="never-index")

    p_list = sub.add_parser("list", help="List managed repositories as JSON")
    p_list.set_defaults(func=cmd_repo_lifecycle, command="list")

    p_set = sub.add_parser(
        "settings",
        help="Show/set registration mode (automatic | mcp_cli) and indexing prefs",
    )
    p_set.add_argument("--show", action="store_true", help="Print prefs.json")
    p_set.add_argument(
        "--mode",
        choices=["automatic", "mcp_cli"],
        default=None,
        help="Project registration mode",
    )
    p_set.add_argument(
        "--incremental",
        type=lambda s: str(s).lower() in {"1", "true", "yes", "on"},
        default=None,
        help="Enable incremental keeper after register (true/false)",
    )
    p_set.add_argument(
        "--watching",
        type=lambda s: str(s).lower() in {"1", "true", "yes", "on"},
        default=None,
        help="Enable file watching / keeper (true/false)",
    )
    p_set.set_defaults(func=cmd_settings)

    p_search = sub.add_parser("search", help="Search with D_rerank (uses warm server if up)")
    p_search.add_argument("query")
    p_search.add_argument("path", nargs="?", default=".")
    p_search.add_argument("--top-k", type=int, default=8)
    p_search.add_argument(
        "--local",
        action="store_true",
        help="Skip HTTP server; use in-process warm cache",
    )
    p_search.add_argument("--url", default="http://127.0.0.1:8765")
    p_search.set_defaults(func=cmd_search)

    p_status = sub.add_parser("status", help="Show index + freshness status")
    p_status.add_argument("path", nargs="?", default=".")
    p_status.add_argument("--url", default="http://127.0.0.1:8765")
    p_status.set_defaults(func=cmd_status)

    p_sync = sub.add_parser("sync", help="Incremental re-embed files changed since last index")
    p_sync.add_argument("path", nargs="?", default=".")
    p_sync.set_defaults(func=cmd_sync)

    p_serve = sub.add_parser("serve", help="Alias: run Context Engine HTTP daemon (foreground)")
    p_serve.add_argument("path", nargs="?", default=".")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.set_defaults(func=cmd_serve)

    p_dashboard = sub.add_parser(
        "dashboard",
        help="Start or control the dedicated localhost operator dashboard",
    )
    p_dashboard.add_argument("action", nargs="?", choices=["stop"], default=None)
    p_dashboard.add_argument(
        "--no-open",
        action="store_true",
        help="Start or reuse the dashboard without opening a browser",
    )
    p_dashboard.add_argument(
        "--status",
        action="store_true",
        help="Print dashboard URL, PID, and health",
    )
    p_dashboard.set_defaults(func=cmd_dashboard)

    p_eng = sub.add_parser("engine", help="Context Engine daemon: start|stop|status|run|ensure")
    p_eng.add_argument(
        "action",
        choices=[
            "start",
            "stop",
            "status",
            "run",
            "ensure",
            "watchdog",
            "supervisor",
            "autostart",
        ],
        help="Daemon action (supervisor = logon loop; watchdog = in-session sidecar)",
    )
    p_eng.add_argument("path", nargs="?", default=".", help="Default repo for open")
    p_eng.add_argument("--host", default="127.0.0.1")
    p_eng.add_argument("--port", type=int, default=8765)
    p_eng.add_argument("--wait", type=float, default=90.0, help="Health wait seconds (start)")
    p_eng.add_argument("--no-open", action="store_true", help="run: do not open repo on start")
    p_eng.add_argument(
        "--logon",
        action="store_true",
        help="supervisor: enter standby and stop leftover GPU (scheduled-task path)",
    )
    p_eng.add_argument(
        "--off",
        action="store_true",
        help="autostart: unregister the logon supervisor task",
    )
    p_eng.set_defaults(func=cmd_engine)

    p_mcp = sub.add_parser("mcp", help="Thin MCP adapter (forwards to Context Engine daemon)")
    p_mcp.add_argument("path", nargs="?", default=None, help="Repo CTX_REPO")
    p_mcp.set_defaults(func=cmd_mcp)

    p_init = sub.add_parser(
        "init",
        help="Enroll a repository under Context Engine and index it",
    )
    p_init.add_argument("path", nargs="?", default=".", help="Repo path (default: cwd)")
    p_init.add_argument("--no-index", action="store_true", help="Manage without indexing")
    p_init.add_argument(
        "--allow-once",
        action="store_true",
        help="Do not persist always-allow registration consent",
    )
    p_init.add_argument(
        "--fast",
        action="store_true",
        help="Fast index: .py under CTX_FAST_ROOTS / --roots only",
    )
    p_init.add_argument(
        "--roots",
        default=None,
        help="Comma-separated fast roots (implies --fast)",
    )
    p_init.set_defaults(func=cmd_init)

    p_setup = sub.add_parser(
        "setup",
        help="One-time machine install: detect GPU, install runtime, calibrate batch, register logon supervisor, write MCP",
    )
    p_setup.add_argument(
        "--profile",
        choices=["cuda", "dml", "coreml", "cpu"],
        default=None,
        help="Force accel profile (default: auto-detect)",
    )
    p_setup.add_argument("--skip-install", action="store_true")
    p_setup.add_argument("--skip-model", action="store_true")
    p_setup.add_argument("--skip-bench", action="store_true")
    p_setup.add_argument("--skip-accel", action="store_true", help="Skip pip/ORT install")
    p_setup.add_argument(
        "--repair",
        action="store_true",
        help="Re-run hardware detection, package/provider setup, and batch calibration",
    )
    p_setup.add_argument(
        "--index",
        dest="index_path",
        default=None,
        help="Also register+index this path after setup",
    )
    p_setup.add_argument(
        "--repo",
        default=".",
        help="Default repo for engine + MCP (default: cwd)",
    )
    p_setup.add_argument("--register", action="store_true", help="Register --repo after start")
    p_setup.add_argument("--host", default="127.0.0.1")
    p_setup.add_argument("--port", type=int, default=8765)
    p_setup.add_argument("--wait", type=float, default=120.0)
    p_setup.add_argument("--status", action="store_true", help="Print saved preferred profile")
    p_setup.set_defaults(func=cmd_setup)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
