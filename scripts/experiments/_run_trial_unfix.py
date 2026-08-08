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


_SURFACE_TOOLS = {
    "read": {"search", "read", "status"},
    "graph": {"search", "neighbors", "graph", "status"},
    "rich": {
        "search", "grep", "usages", "read", "expand", "outline",
        "neighbors", "graph", "imports", "status",
    },
    "search": {"search", "status"},
    "grep": {"grep", "status"},
}
_SURFACE_MARKERS = {
    "read": ('_tool("search"', '_tool("read"'),
    "graph": ('_tool("search"', '_tool("neighbors"', '_tool("graph"'),
    "rich": (
        '_tool("search"', '_tool("grep"', '_tool("usages"', '_tool("read"',
        '_tool("outline"', '_tool("imports"',
    ),
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
                res = _json.loads(grep_fn(pattern="def search", glob="*.py"))
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
                    search_fn(query="focus function query and path handling", k=5)
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
                    grep_fn = mcp._tool_manager._tools["grep"].fn
                    grep_res = _json.loads(grep_fn(pattern="def search", glob="*.py"))
                    probe_ok = probe_ok and bool(grep_res.get("ok"))
                    note += f" grep_hits={grep_res.get('count')}"
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


TRIAL_MARKER = "ce_dev_trial"


def kill_stale_trial_engines() -> None:
    """Kill leftover engine daemons and MCP servers bound to previous trial
    workspaces. These re-point the shared port-8765 engine at dead workspaces and
    hold the temp index mmap — the root cause of `engine serves <old ws>` and
    "still-locked" temp dirs.

    IMPORTANT: the CE arm's ``pipeline.mcp_locate`` receives its workspace via the
    ``CTX_REPO`` **environment variable**, not the command line, so a cmdline-only
    match silently misses it (only graphify's graph_json path is on the cmdline).
    We therefore inspect each process's cmdline AND environment, keying on the
    trial temp root (``ce_dev_trial``). Cursor's own MCP — whose ``CTX_REPO`` is
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


def preflight(arm_names: tuple[str, ...]) -> int:
    """Exercise the ENTIRE non-agent path for each arm, for free, so setup bugs
    surface without spending on a paid agent run:
      copy + un-fix -> baseline hash parity -> index -> (context_engine) ensure
      engine repo -> baseline pytest -> git diff -> evaluate. No agent.send.
    """
    kill_stale_trial_engines()
    output = trial._default_output().resolve()
    output = output.parent / (output.name + "_preflight")
    output.mkdir(parents=True, exist_ok=True)
    python = trial._source_python(ROOT)
    print(f"[preflight] output={output} arms={arm_names}", flush=True)

    workspaces: dict[str, Path] = {}
    for name in arm_names:
        ws = output / f"{name}_workspace"
        print(f"[preflight] {name}: copy", flush=True)
        trial.copy_workspace(ROOT, ws)
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
            graph = trial.index_workspace(ws, python, ROOT)
            cfg = smoke.build_configs(ROOT, ws, python, graph)[name]
            if name != "graphify":
                trial._clear_context_state(ws)
                smoke.ensure_engine_repo(ws)
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
            passed = bool(tests.get("passed"))
            print(
                f"[preflight] {name}: pytest_passed={passed} "
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
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    arm_names = tuple(a.strip() for a in str(args.arms).split(",") if a.strip())

    if args.preflight:
        return preflight(arm_names)

    api_key = smoke.load_cursor_api_key(ROOT)
    if not api_key:
        print("ERROR: no CURSOR_API_KEY", file=sys.stderr, flush=True)
        return 2
    os.environ["CURSOR_API_KEY"] = api_key
    kill_stale_trial_engines()
    output = trial._default_output().resolve()
    print(f"[trial] output={output} arms={arm_names} timeout={args.timeout:g}s", flush=True)
    data = asyncio.run(
        trial.run_trial(ROOT, output, "composer-2.5", args.timeout, arm_names=arm_names)
    )
    for name, arm in data["arms"].items():
        usage = arm.get("usage") or {}
        print(
            f"[trial] {name}: status={arm.get('status')} "
            f"work_complete={arm.get('work_complete')} "
            f"quality_pass={arm.get('quality_pass')} "
            f"total_tokens={usage.get('total_tokens')} "
            f"error={str(arm.get('error') or '')[:80]!r}",
            flush=True,
        )
    print(f"[trial] REPORT: {output / 'REPORT.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
