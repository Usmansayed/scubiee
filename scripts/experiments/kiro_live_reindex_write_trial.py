"""Small Kiro write → CE live-reindex → find trial on ce-sim fixture.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts/experiments/kiro_live_reindex_write_trial.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "scripts" / "experiments"))

import kiro_mcp_preflight as pf  # noqa: E402
import kiro_trial as kt  # noqa: E402
from pipeline.client import EngineClient  # noqa: E402
from pipeline.daemon import ensure_daemon, start_daemon, stop_daemon  # noqa: E402


MARKER = f"kiro_live_marker_{int(time.time())}"


def _python() -> str:
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv if venv.is_file() else sys.executable)


def _seed(ws: Path) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    auth = subprocess.check_output(
        ["git", "show", "HEAD:fixtures/ce-sim-repo/auth.py"],
        cwd=str(ROOT),
        text=True,
    )
    session = subprocess.check_output(
        ["git", "show", "HEAD:fixtures/ce-sim-repo/session.py"],
        cwd=str(ROOT),
        text=True,
    )
    (ws / "auth.py").write_text(auth, encoding="utf-8")
    (ws / "session.py").write_text(session, encoding="utf-8")
    subprocess.run(["git", "init"], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=str(ws), check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=kiro@local",
            "-c",
            "user.name=kiro",
            "commit",
            "-m",
            "seed",
        ],
        cwd=str(ws),
        check=True,
        capture_output=True,
    )


def main() -> int:
    pf.load_dotenv_keys(ROOT / ".env")
    kt.ensure_api_key()

    home = Path(tempfile.mkdtemp(prefix="ce_kiro_live_home_"))
    ws = Path(tempfile.mkdtemp(prefix="ce_kiro_live_ws_"))
    os.environ["CTX_HOME"] = str(home)
    os.environ["CTX_BACKGROUND_SYNC"] = "1"
    os.environ["CTX_DEBOUNCE_MS"] = "800"
    os.environ["CTX_REWRITE_DEBOUNCE_MS"] = "1200"
    os.environ["CTX_LOCATE_STREAK_MS"] = "1500"
    os.environ["CTX_SYNC_INITIAL_DELAY_MS"] = "200"
    os.environ["CTX_SYNC_INTERVAL_MS"] = "60000"
    os.environ["CTX_CHANGE_POLL_MS"] = "1000"
    os.environ["CTX_MCP_SURFACE"] = "read"
    os.environ["PYTHONPATH"] = str(ROOT / "packages")
    os.environ["CTX_REPO"] = str(ws)

    print(json.dumps({"step": "seed", "ws": str(ws), "home": str(home), "marker": MARKER}, indent=2), flush=True)
    _seed(ws)

    print(json.dumps({"step": "index"}, indent=2), flush=True)
    subprocess.run(
        [_python(), "-m", "pipeline", "index", str(ws), "--fast", "--force"],
        cwd=str(ROOT),
        env={**os.environ},
        check=True,
    )

    try:
        stop_daemon()
    except Exception:
        pass
    started = start_daemon(ws)
    ensure_daemon(ws)
    client = EngineClient()
    open_res = client.open_repo(str(ws), wait=True)
    print(json.dumps({"step": "engine", "started": started.get("ok"), "open_ok": open_res.get("ok"), "generation": open_res.get("generation") or client.status(str(ws)).get("generation")}, indent=2), flush=True)

    # Kiro MCP + steering for CE search surface.
    kt.write_steering(ws, "ce_search")
    kt.write_arm_mcp(ws, "ce_search")

    prompt = f"""
You are testing Context Engine live reindexing.

1) Edit auth.py: append a new Python function named {MARKER} that returns the string "{MARKER}".
2) Save the file.
3) Wait about 5 seconds (do not keep editing).
4) Use Context Engine MCP search to find "{MARKER}" (search surface tool name: search). If only map/focus exist, use those.
5) Reply with exactly one of:
   CE_FOUND: <file>:<line>
   CE_MISSING: <brief reason>
Also mention any CE tool names you used.
""".strip()

    model = kt.resolve_model(os.environ.get("KIRO_TRIAL_MODEL") or "gpt-5.6-luna")
    print(json.dumps({"step": "kiro_start", "model": model}, indent=2), flush=True)
    raw = kt.run_kiro(
        workspace=ws,
        prompt=prompt,
        model=model,
        timeout_s=240.0,
        require_mcp=True,
    )
    blob = "\n".join([raw.get("stdout") or "", raw.get("stderr") or "", raw.get("log") or ""])
    tools = kt.scrape_tool_calls(blob)

    # Independent CE verification after Kiro finishes.
    time.sleep(8.0)
    st = client.status(str(ws))
    search = client.search(MARKER, top_k=8, path=str(ws))
    hits = search.get("hits") or search.get("results") or []
    why = " ".join(str(h.get("why") or "") for h in hits)
    auth_text = (ws / "auth.py").read_text(encoding="utf-8", errors="replace")
    wrote = MARKER in auth_text
    indexed = MARKER in why or any(MARKER in json.dumps(h) for h in hits)

    out_dir = ROOT / "out" / "kiro_live_reindex"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "ok": bool(wrote and indexed and raw.get("status") == "finished"),
        "marker": MARKER,
        "workspace": str(ws),
        "kiro_status": raw.get("status"),
        "kiro_returncode": raw.get("returncode"),
        "kiro_error": (raw.get("error") or "")[:500],
        "wall_s": round(float(raw.get("wall_s") or 0), 2),
        "wrote_marker_to_disk": wrote,
        "ce_indexed_marker": indexed,
        "generation": st.get("generation"),
        "keeper": st.get("keeper"),
        "search_hits": hits[:5],
        "tool_calls": tools[:40],
        "out_tail": blob[-2000:],
    }
    path = out_dir / f"{MARKER}.json"
    path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out_dir / f"{MARKER}.stdout.txt").write_text(blob, encoding="utf-8", errors="replace")
    print(json.dumps({k: summary[k] for k in summary if k not in {"out_tail", "keeper"}}, indent=2, default=str), flush=True)
    print(f"REPORT → {path}", flush=True)
    print("--- tail ---", flush=True)
    print(blob[-1500:], flush=True)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
