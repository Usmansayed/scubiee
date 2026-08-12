"""Run the 2-arm dev trial (Context Engine vs Graphify) with a clean baseline.

The task is now a genuine multi-file FEATURE build (query expansion for search),
so there is no bug to reintroduce — each arm starts from an identical clean copy
of the source tree and must implement the feature across pipeline + MCP + CLI +
tests + docs. This runner keeps the shared preflight gate, the stale-engine
cleanup, and the live MCP `search` verification.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod  # type: ignore[union-attr]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


smoke = _load("_smoke_unfix", Path(__file__).with_name("sdk_mcp_smoke.py"))
trial = _load("_trial_unfix", Path(__file__).with_name("sdk_mcp_dev_trial.py"))

# Profile-specific live probes for the preflight. "ce" self-trial edits this
# repo's own MCP source (so we can assert source parity); "frontend" runs against
# a different repo, so we probe with repo-appropriate queries and skip the
# self-edit parity guard.
_PROFILE = (os.environ.get("CTX_TRIAL_PROFILE") or "ce").strip().lower()
_PROBES = {
    "ce": {
        "search": "focus function query and path handling",
        "grep": "def search",
        "files": "mcp_locate.py",
        "self_edit": True,
    },
    "frontend": {
        "search": "where MCP tools are registered and dispatched by name",
        "grep": "def handle_",
        "files": "tools.py",
        "self_edit": False,
    },
}
_PROBE = _PROBES.get(_PROFILE, _PROBES["ce"])


_SURFACE_TOOLS = {
    "read": {"search", "read", "status"},
    "nav": {"search", "files", "read", "recall", "expand", "status"},
    "graph": {"search", "neighbors", "graph", "status"},
    "rich": {"search", "read", "outline", "status"},
    "search": {"search", "status"},
    "grep": {"grep", "status"},
}
_SURFACE_MARKERS = {
    "read": ('_tool("search"', '_tool("read"'),
    "nav": ('_tool("search"', '_tool("files"', '_tool("read"', '_tool("recall"', '_tool("expand"'),
    "graph": ('_tool("search"', '_tool("neighbors"', '_tool("graph"'),
    "rich": ('_tool("search"', '_tool("read"', '_tool("outline"'),
    "search": ('_tool("search"', '_tool("status"'),
    "grep": ('_tool("grep"', '_tool("status"'),
}


def verify_mcp_search(ws: Path, surface: str) -> None:
    """Prove the (source) Context Engine MCP serves the expected tool surface and
    that the live tools work against this workspace. Runs in-process from source,
    so a broken tool fails loudly here — for free — instead of the agent hitting
    it mid-run. Requires the engine to already be pointed at `ws`.
    """
    import json as _json

    from pipeline.mcp_locate import create_mcp

    surface = surface if surface in _SURFACE_TOOLS else "read"
    prev_surface = os.environ.get("CTX_MCP_SURFACE")
    os.environ["CTX_MCP_SURFACE"] = surface

    prev = os.environ.get("CTX_REPO")
    os.environ["CTX_REPO"] = str(ws)
    res: dict = {}
    probe_ok = True
    probe1: dict = {}
    probe2: dict = {}
    note = "search-only"
    try:
        mcp = create_mcp()
        tools = set(mcp._tool_manager._tools)
        expected = _SURFACE_TOOLS[surface]
        if tools != expected:
            raise SystemExit(
                f"ABORT: MCP surface drifted ({surface}); expected exactly "
                f"{sorted(expected)}, got {sorted(tools)}"
            )
        # Assert the COPY the agent edits has the tools (source parity guard).
        # Only meaningful when the workspace IS this repo (ce self-trial); the
        # frontend profile edits a different repo with no mcp_locate.py.
        if _PROBE["self_edit"]:
            copy_src = (ws / "packages" / "pipeline" / "mcp_locate.py").read_text(
                encoding="utf-8"
            )
            for needed in _SURFACE_MARKERS[surface]:
                if needed not in copy_src:
                    raise SystemExit(
                        f"ABORT: workspace copy of mcp_locate.py lacks {needed}"
                    )

        deadline = time.time() + 180.0
        if surface == "grep":
            # No search tool on this surface — prove the live grep works instead.
            grep_fn = mcp._tool_manager._tools["grep"].fn
            while time.time() < deadline:
                res = _json.loads(grep_fn(pattern=_PROBE["grep"], glob="*.py"))
                if res.get("ok") and res.get("count"):
                    break
                time.sleep(5.0)
            probe_ok = bool(res.get("ok") and res.get("count"))
            note = f"grep_hits={res.get('count')}"
            res.setdefault("results", res.get("hits") or [])

        else:
            search_fn = mcp._tool_manager._tools["search"].fn
            # The engine warms asynchronously after ensure_engine_repo; retry
            # until a live semantic search returns hits (or abort loudly).
            while time.time() < deadline:
                res = _json.loads(
                    search_fn(query=_PROBE["search"], k=5)
                )
                if res.get("ok") and res.get("results"):
                    break
                time.sleep(5.0)

        if surface != "grep" and res.get("results"):
            top_file = res["results"][0].get("file")
            if surface == "graph":
                nbr_fn = mcp._tool_manager._tools["neighbors"].fn
                gph_fn = mcp._tool_manager._tools["graph"].fn
                probe1 = _json.loads(nbr_fn(target=str(top_file)))
                probe2 = _json.loads(gph_fn(question="how is a search query processed"))
                probe_ok = bool(probe1.get("ok") and probe2.get("ok"))
                note = f"neighbors={probe1.get('count')} graph={probe2.get('count')}"
            elif surface == "nav":
                read_fn = mcp._tool_manager._tools["read"].fn
                files_fn = mcp._tool_manager._tools["files"].fn
                recall_fn = mcp._tool_manager._tools["recall"].fn
                expand_fn = mcp._tool_manager._tools["expand"].fn
                probe1 = _json.loads(read_fn(target=str(top_file)))
                probe2 = _json.loads(read_fn(target=str(top_file)))
                files_res = _json.loads(files_fn(pattern="."))
                recall_res = _json.loads(recall_fn())
                expand_ok = True
                if probe1.get("handle"):
                    expand_res = _json.loads(expand_fn(handle=str(probe1["handle"])))
                    expand_ok = bool(expand_res.get("ok"))
                exact = _json.loads(search_fn(query=_PROBE["grep"], mode="exact", k=5))
                probe_ok = bool(
                    probe1.get("ok")
                    and probe1.get("handle")
                    and probe2.get("handle") == probe1.get("handle")
                    and probe2.get("unchanged") is True
                    and files_res.get("ok")
                    and recall_res.get("ok")
                    and expand_ok
                    and exact.get("ok")
                )
                note = (
                    f"read_handle={probe1.get('handle')} dedupe=unchanged "
                    f"files_ok={files_res.get('ok')} recall={recall_res.get('count')} "
                    f"exact_hits={exact.get('count')} expand_ok={expand_ok}"
                )
            elif surface in {"read", "rich"}:
                read_fn = mcp._tool_manager._tools["read"].fn
                probe1 = _json.loads(read_fn(target=str(top_file)))
                probe2 = _json.loads(read_fn(target=str(top_file)))
                probe_ok = bool(
                    probe1.get("ok")
                    and probe1.get("handle")
                    and probe2.get("handle") == probe1.get("handle")
                    and probe2.get("unchanged") is True
                )
                note = f"read_handle={probe1.get('handle')} dedupe=unchanged"
                if surface == "rich":
                    # Value-add surface: prove outline (structure) + the graph via
                    # read(neighbors=true). grep/files are gone — native handles
                    # exact strings / filenames now.
                    outline_fn = mcp._tool_manager._tools["outline"].fn
                    outline_res = _json.loads(outline_fn(path=str(top_file)))
                    nbr_res = _json.loads(
                        read_fn(path=str(top_file), neighbors=True, max_neighbors=3)
                    )
                    nbr_ok = bool(nbr_res.get("ok")) and (
                        "neighbors" in nbr_res or "neighbors_note" in nbr_res
                    )
                    probe_ok = probe_ok and bool(outline_res.get("ok")) and nbr_ok
                    note += (
                        f" outline_ok={outline_res.get('ok')} "
                        f"read_neighbors={nbr_res.get('neighbors_count', 0)}"
                    )
            else:  # search-only: the live search above is the whole surface
                probe_ok = bool(res.get("ok"))
    finally:
        if prev is None:
            os.environ.pop("CTX_REPO", None)
        else:
            os.environ["CTX_REPO"] = prev
        if prev_surface is None:
            os.environ.pop("CTX_MCP_SURFACE", None)
        else:
            os.environ["CTX_MCP_SURFACE"] = prev_surface

    if not res.get("ok") or not res.get("results"):
        raise SystemExit(
            f"ABORT: live search returned no results after warm wait: {res}"
        )
    if not probe_ok:
        raise SystemExit(
            f"ABORT: {surface} tool probe failed: p1={probe1} p2={probe2}"
        )
    print(
        f"[preflight] MCP {surface} surface OK: {res.get('count')} hits, "
        f"top={res['results'][0].get('file')}, {note}",
        flush=True,
    )


def verify_cbm_ce(ws: Path) -> None:
    """Prove hybrid facade: CE soft search + one CBM graph call."""
    import json as _json

    from hybrid_cbm.proxy import make_proxy, resolve_project_name
    from hybrid_cbm.server import create_mcp

    prev = os.environ.get("CTX_REPO")
    os.environ["CTX_REPO"] = str(ws)
    try:
        mcp = create_mcp()
        tools = set(mcp._tool_manager._tools)
        expected = {
            "search",
            "search_graph",
            "trace_path",
            "get_code_snippet",
            "status",
        }
        if tools != expected:
            raise SystemExit(
                f"ABORT: cbm_ce surface drifted; expected {sorted(expected)}, "
                f"got {sorted(tools)}"
            )
        search_fn = mcp._tool_manager._tools["search"].fn
        deadline = time.time() + 180.0
        res: dict = {}
        while time.time() < deadline:
            res = _json.loads(search_fn(query=_PROBE["search"], k=5))
            if res.get("ok") and res.get("results"):
                break
            time.sleep(5.0)
        if not res.get("ok") or not res.get("results"):
            raise SystemExit(
                f"ABORT: cbm_ce soft search returned no results after warm wait: {res}"
            )
        proxy = make_proxy()
        if not proxy.available():
            raise SystemExit(
                "ABORT: CBM binary not found for cbm_ce preflight "
                "(install codebase-memory-mcp or set CTX_CBM_BIN)"
            )
        project = resolve_project_name(proxy, ws)
        sg_fn = mcp._tool_manager._tools["search_graph"].fn
        # Broad pattern so tiny fixtures still return something after index.
        sg = _json.loads(sg_fn(name_pattern=".*", project=project, limit=5))
        if not sg.get("ok"):
            raise SystemExit(f"ABORT: cbm_ce search_graph failed: {sg}")
        print(
            f"[preflight] MCP cbm_ce OK: soft_hits={res.get('count')} "
            f"top={res['results'][0].get('file')} "
            f"graph_total={sg.get('total')} project={project}",
            flush=True,
        )
    finally:
        if prev is None:
            os.environ.pop("CTX_REPO", None)
        else:
            os.environ["CTX_REPO"] = prev


TRIAL_MARKER = "ce_iso_trial"


def kill_stale_trial_engines() -> None:
    """Kill leftover engine daemons and MCP servers bound to previous trial
    workspaces. These re-point the shared port-8765 engine at dead workspaces and
    hold the temp index mmap — the root cause of `engine serves <old ws>` and
    "still-locked" temp dirs.

    IMPORTANT: the CE arm's ``pipeline.mcp_locate`` receives its workspace via the
    ``CTX_REPO`` **environment variable**, not the command line, so a cmdline-only
    match silently misses it (only graphify's graph_json path is on the cmdline).
    We therefore inspect each process's cmdline AND environment, keying on the
    trial temp root (``ce_iso_trial``). Cursor's own MCP — whose ``CTX_REPO`` is
    the real repo — never matches, so it is left untouched.
    """
    killed = 0
    try:
        import psutil  # local import: only needed for cleanup
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] psutil unavailable ({exc}); skipping precise kill", flush=True)
        psutil = None  # type: ignore[assignment]

    if psutil is not None:
        for proc in psutil.process_iter(["pid", "name", "cmdline", "environ"]):
            try:
                info = proc.info
                cmdline = " ".join(info.get("cmdline") or [])
                if not (
                    "pipeline.mcp_locate" in cmdline
                    or "pipeline.engine" in cmdline
                    or "graphify.serve" in cmdline
                ):
                    continue
                environ = info.get("environ") or {}
                repo = str(environ.get("CTX_REPO") or "")
                hay = f"{cmdline}\n{repo}".replace("\\", "/")
                if TRIAL_MARKER not in hay:
                    continue  # not a trial process (e.g. Cursor's live MCP)
                proc.kill()
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):  # type: ignore[union-attr]
                continue
            except Exception:  # noqa: BLE001
                continue

    # Also stop the currently-tracked daemon so ensure_engine_repo starts clean.
    try:
        from pipeline.daemon import stop_daemon

        stop_daemon()
    except Exception:  # noqa: BLE001
        pass
    print(
        f"[cleanup] killed {killed} stale trial engine/mcp proc(s); "
        "stopped tracked daemon",
        flush=True,
    )


def preflight(arm_names: tuple[str, ...], source: Path | None = None) -> int:
    """Exercise the ENTIRE non-agent path for each arm, for free, so setup bugs
    surface without spending on a paid agent run:
      copy -> baseline hash parity -> index -> (context_engine) ensure engine repo
      -> live MCP probe -> post-tests -> git diff -> evaluate. No agent.send.

    ``source`` is the repo copied/indexed/given to the agent (default: this repo).
    Tooling (pipeline/graphify/venv) always comes from ROOT.
    """
    source = (source or ROOT).resolve()
    kill_stale_trial_engines()
    output = trial._default_output().resolve()
    output = output.parent / (output.name + "_preflight")
    output.mkdir(parents=True, exist_ok=True)
    python = trial._source_python(ROOT)
    print(f"[preflight] output={output} arms={arm_names} source={source}", flush=True)

    workspaces: dict[str, Path] = {}
    for name in arm_names:
        ws = output / f"{name}_workspace"
        print(f"[preflight] {name}: copy", flush=True)
        trial.copy_workspace(source, ws)
        workspaces[name] = ws

    hashes = {n: trial.source_tree_hash(w) for n, w in workspaces.items()}
    if len(set(hashes.values())) != 1:
        print(f"[preflight] FAIL: baseline tree hashes differ: {hashes}", flush=True)
        return 1
    print("[preflight] baseline hash parity OK", flush=True)

    ok = True
    for name, ws in workspaces.items():
        t0 = time.perf_counter()
        try:
            if name == "raw":
                # No MCP / no graph — skip index + engine; prove empty providers.
                graph = ws / ".context-engine" / "graph.json"
                cfg = smoke.build_configs(ROOT, ws, python, graph)[name]
                if cfg.mcp_servers:
                    raise RuntimeError(
                        f"raw arm must have zero MCP servers, "
                        f"got {sorted(cfg.mcp_servers)}"
                    )
                print(
                    "[preflight] raw: no MCP servers (native-only baseline) OK",
                    flush=True,
                )
            else:
                graph = trial.index_workspace(ws, python, ROOT)
                if name == "cbm_ce":
                    trial.index_cbm_workspace(ws)
                cfg = smoke.build_configs(ROOT, ws, python, graph)[name]
                if name != "graphify":
                    trial._clear_context_state(ws)
                    smoke.ensure_engine_repo(ws)
                    if name == "cbm_ce":
                        verify_cbm_ce(ws)
                    else:
                        verify_mcp_search(ws, smoke.arm_surface(name))
            tests = trial.run_post_tests(ws, python, ROOT, arm=name)
            diff = trial.git_diff(ws)
            outcome = trial.evaluate_development_arm(
                name,
                "finished",
                [],
                {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                diff,
                tests,
            )
            dt = time.perf_counter() - t0
            # A skipped suite (frontend profile: target-repo deps absent) is not a
            # failure — scoring there is by task shape, verified live above.
            skipped = bool(tests.get("skipped"))
            passed = True if skipped else bool(tests.get("passed"))
            print(
                f"[preflight] {name}: pytest_passed={'skipped' if skipped else passed} "
                f"exit={tests.get('exit_code')} baseline_diff_empty={not diff.strip()} "
                f"mcp_servers={sorted(cfg.mcp_servers)} took={dt:.1f}s",
                flush=True,
            )
            if not passed:
                ok = False
                print(f"[preflight] {name}: pytest stderr/stdout tail:", flush=True)
                print(str(tests.get("stdout") or "")[-600:], flush=True)
                print(str(tests.get("stderr") or "")[-600:], flush=True)
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"[preflight] {name}: FAIL {type(exc).__name__}: {exc}", flush=True)

    print(f"[preflight] {'PASS' if ok else 'FAIL'}", flush=True)
    return 0 if ok else 1


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--arms", default=",".join(trial.ARM_NAMES))
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--model", default="auto")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument(
        "--prompt-id",
        default="",
        help="frontend prompt: thrash|degraded|consistency|combo (sets CTX_FRONTEND_PROMPT)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT,
        help="Repo to copy/index/give the agent (default: this repo). Tooling "
        "always stays this repo; set CTX_TRIAL_PROFILE=frontend to match.",
    )
    args = parser.parse_args()
    arm_names = tuple(a.strip() for a in str(args.arms).split(",") if a.strip())
    source = args.source.resolve()

    if args.prompt_id:
        pid = str(args.prompt_id).strip().lower()
        if pid not in trial.FRONTEND_PROMPTS:
            print(
                f"ERROR: --prompt-id must be one of {sorted(trial.FRONTEND_PROMPTS)}",
                file=sys.stderr,
                flush=True,
            )
            return 2
        os.environ["CTX_FRONTEND_PROMPT"] = pid

    if args.preflight:
        return preflight(arm_names, source)

    api_key = smoke.load_cursor_api_key(ROOT)
    if not api_key:
        print("ERROR: no CURSOR_API_KEY", file=sys.stderr, flush=True)
        return 2
    os.environ["CURSOR_API_KEY"] = api_key
    kill_stale_trial_engines()
    output = trial._default_output().resolve()
    print(
        f"[trial] output={output} arms={arm_names} source={source} "
        f"model={args.model} timeout={args.timeout:g}s "
        f"prompt={(os.environ.get('CTX_FRONTEND_PROMPT') or '')}",
        flush=True,
    )
    data = asyncio.run(
        trial.run_trial(source, output, args.model, args.timeout, arm_names=arm_names)
    )
    for name, arm in data["arms"].items():
        usage = arm.get("usage") or {}
        work = arm.get("work_tokens")
        if work is None:
            inp, out = usage.get("input_tokens"), usage.get("output_tokens")
            work = (inp or 0) + (out or 0) if inp is not None and out is not None else None
        print(
            f"[trial] {name}: status={arm.get('status')} "
            f"work_complete={arm.get('work_complete')} "
            f"quality_pass={arm.get('quality_pass')} "
            f"work_tokens={work} "
            f"total_tokens={usage.get('total_tokens')} "
            f"mcp_disc={arm.get('mcp_discovery_count')} "
            f"used_task={arm.get('used_task')} "
            f"error={str(arm.get('error') or '')[:80]!r}",
            flush=True,
        )
    print(f"[trial] REPORT: {output / 'REPORT.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
