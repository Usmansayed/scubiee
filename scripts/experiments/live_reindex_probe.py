"""Manual live-reindex probe: write into an indexed tiny repo and verify search.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts/experiments/live_reindex_probe.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

MARKER = f"live_reindex_probe_{int(time.time())}"


def _python() -> str:
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv if venv.is_file() else sys.executable)


def _seed_workspace(ws: Path) -> None:
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
        ["git", "-c", "user.email=probe@local", "-c", "user.name=probe", "commit", "-m", "seed"],
        cwd=str(ws),
        check=True,
        capture_output=True,
    )


def main() -> int:
    from pipeline.client import EngineClient
    from pipeline.daemon import ensure_daemon, start_daemon, stop_daemon
    from pipeline.live_reindex import notify_changed_files

    home = Path(tempfile.mkdtemp(prefix="ce_live_home_"))
    os.environ["CTX_HOME"] = str(home)
    os.environ["CTX_BACKGROUND_SYNC"] = "1"
    os.environ["CTX_DEBOUNCE_MS"] = "500"
    os.environ["CTX_REWRITE_DEBOUNCE_MS"] = "800"
    os.environ["CTX_LOCATE_STREAK_MS"] = "500"
    os.environ["CTX_SYNC_INITIAL_DELAY_MS"] = "200"
    os.environ["CTX_SYNC_INTERVAL_MS"] = "60000"
    os.environ["PYTHONPATH"] = str(ROOT / "packages")

    ws = Path(tempfile.mkdtemp(prefix="ce_live_probe_"))
    report = {
        "workspace": str(ws),
        "ctx_home": str(home),
        "marker": MARKER,
        "ok": False,
    }
    print(json.dumps({"step": "seed", "workspace": str(ws), "ctx_home": str(home)}, indent=2), flush=True)
    _seed_workspace(ws)

    print(json.dumps({"step": "index"}, indent=2), flush=True)
    subprocess.run(
        [_python(), "-m", "pipeline", "index", str(ws), "--fast", "--force"],
        cwd=str(ROOT),
        env={**os.environ},
        check=True,
    )

    print(json.dumps({"step": "start_daemon"}, indent=2), flush=True)
    try:
        stop_daemon()
    except Exception:
        pass
    started = start_daemon(ws)
    ensure_daemon(ws)
    client = EngineClient()
    open_res = client.open_repo(str(ws), wait=True)
    report["open"] = {k: open_res.get(k) for k in ("ok", "repo", "generation", "warm_state", "error") if k in open_res or True}
    status0 = client.status(str(ws))
    report["status_before"] = {
        "generation": status0.get("generation"),
        "repo": status0.get("repo"),
        "keeper": (status0.get("keeper") or status0.get("sync") or {}),
    }
    gen0 = int(status0.get("generation") or 0)

    # Baseline: marker should NOT be findable yet.
    before = client.search(MARKER, top_k=5, path=str(ws))
    report["search_before"] = {
        "ok": before.get("ok", True),
        "count": len(before.get("results") or before.get("hits") or []),
        "top": [
            {
                "file": r.get("file") or r.get("path"),
                "score": r.get("score"),
            }
            for r in (before.get("results") or before.get("hits") or [])[:3]
        ],
    }

    # Write distinctive symbol into an already-indexed file.
    auth_path = ws / "auth.py"
    auth_path.write_text(
        auth_path.read_text(encoding="utf-8")
        + f"\n\ndef {MARKER}() -> str:\n"
        + f'    """Live reindex probe marker."""\n'
        + f'    return "{MARKER}"\n',
        encoding="utf-8",
    )
    print(json.dumps({"step": "wrote", "marker": MARKER}, indent=2), flush=True)

    dirty = notify_changed_files(ws, ["auth.py"], reason="probe_write")
    report["dirty"] = dirty
    print(json.dumps({"step": "dirty", "result": dirty}, indent=2), flush=True)

    # Wait for debounce + sync + optional publish.
    found = False
    timeline = []
    deadline = time.time() + 90.0
    while time.time() < deadline:
        time.sleep(1.0)
        st = client.status(str(ws))
        keeper = st.get("keeper") or st.get("sync") or st.get("sync_loop") or {}
        if not isinstance(keeper, dict):
            keeper = {}
        # Some status payloads nest sync_loop under runtime.
        if not keeper and isinstance(st.get("runtime"), dict):
            keeper = (st["runtime"].get("sync_loop") or {})
        search = client.search(
            f"{MARKER} live reindex probe marker authenticate password",
            top_k=8,
            path=str(ws),
        )
        hits = search.get("results") or search.get("hits") or []
        hit_files = [str(h.get("file") or h.get("path") or "") for h in hits]
        marker_hit = any(MARKER.lower() in json.dumps(h).lower() for h in hits) or any(
            "auth.py" in f.replace("\\", "/") for f in hit_files
        )
        # Stronger check: grep exact via client if available
        grep = {}
        try:
            grep = client.grep(MARKER, glob="*.py", max_hits=5, path=str(ws))
        except TypeError:
            grep = client.grep(MARKER, glob="*.py", max_hits=5)
        grep_hits = grep.get("hits") or grep.get("matches") or []
        exact = any(MARKER in json.dumps(h) for h in grep_hits)
        row = {
            "t": round(time.time(), 2),
            "generation": st.get("generation"),
            "overlay_ready": keeper.get("overlay_ready"),
            "publish_pending": keeper.get("publish_pending"),
            "locate_streak_active": keeper.get("locate_streak_active"),
            "search_count": len(hits),
            "auth_in_hits": any("auth.py" in f.replace("\\", "/") for f in hit_files),
            "exact_grep": exact,
            "dirty_ok": dirty.get("ok"),
        }
        timeline.append(row)
        print(json.dumps({"step": "poll", **row}, indent=2), flush=True)
        if exact or (int(st.get("generation") or 0) > gen0 and marker_hit):
            found = True
            report["search_after"] = {
                "hits": hits[:5],
                "grep_hits": grep_hits[:5],
                "generation": st.get("generation"),
            }
            break

    report["timeline"] = timeline
    report["ok"] = bool(found)
    report["started"] = started
    out = ROOT / "out" / "live_reindex_probe"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"probe_{MARKER}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"step": "done", "ok": report["ok"], "report": str(path)}, indent=2), flush=True)
    print(json.dumps(report, indent=2, default=str)[-2500:], flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
