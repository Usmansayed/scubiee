"""Score Cursor isolated-folder A/B: git diff + pytest + transcript token estimate."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ROOT / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

BASE = ROOT / "out" / "experiments" / "cursor_dev_ab"
TRANSCRIPTS = (
    Path.home()
    / ".cursor"
    / "projects"
    / "c-Users-usman-Downloads-context-engine"
    / "agent-transcripts"
)


def estimate_tokens(text: str) -> int:
    from pipeline.token_meter import estimate_tokens as _e

    return int(_e(text or ""))


def _walk_text(obj) -> str:
    chunks: list[str] = []
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            chunks.append(_walk_text(v))
    elif isinstance(obj, list):
        for v in obj:
            chunks.append(_walk_text(v))
    else:
        chunks.append(str(obj))
    return "\n".join(chunks)


def transcript_tokens(agent_id: str) -> dict:
    # search recursively for agent_id.jsonl
    hits = list(TRANSCRIPTS.rglob(f"{agent_id}.jsonl")) if TRANSCRIPTS.is_dir() else []
    if not hits:
        return {"ok": False, "error": "transcript missing", "tokens": 0, "lines": 0}
    path = hits[0]
    total = 0
    lines = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        lines += 1
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            total += estimate_tokens(line)
            continue
        total += estimate_tokens(_walk_text(ev))
    return {"ok": True, "path": str(path), "tokens": total, "lines": lines}


def meter_summary(arm: str) -> dict:
    path = BASE / "meter" / f"{arm}.jsonl"
    if not path.is_file():
        return {"calls": 0, "tokens_in": 0}
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {
        "calls": len(rows),
        "tokens_in": sum(int(r.get("tokens_in") or 0) for r in rows),
        "tools": [r.get("tool") for r in rows],
    }


def work_quality(work: Path) -> dict:
    test = work / "tests" / "test_browser_session_busy_guidance.py"
    diff = subprocess.run(
        ["git", "diff", "--stat", "HEAD"],
        cwd=str(work),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(work),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # unstaged + untracked as change signal
    changed = bool((status.stdout or "").strip())
    # also check committed? agents may leave uncommitted
    pytest = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_browser_session_busy_guidance.py", "-q"],
        cwd=str(work),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    # content checks on guidance module if present
    guidance_hits = []
    for p in work.rglob("agent_guidance.py"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        guidance_hits.append(
            {
                "path": str(p.relative_to(work)).replace("\\", "/"),
                "has_busy": "browser_session_busy" in txt,
                "has_contention_hint": "def contention_hint" in txt,
            }
        )
    return {
        "test_file_exists": test.is_file(),
        "git_changed": changed,
        "git_diff_stat": (diff.stdout or "")[:500],
        "pytest_ok": pytest.returncode == 0,
        "pytest_out": ((pytest.stdout or "") + (pytest.stderr or ""))[-800:],
        "guidance_hits": guidance_hits,
        "feature_ok": any(h.get("has_busy") and h.get("has_contention_hint") for h in guidance_hits)
        and pytest.returncode == 0,
    }


def score_arm(arm: str, agent_id: str) -> dict:
    work = BASE / f"work_{arm}"
    q = work_quality(work)
    tr = transcript_tokens(agent_id)
    m = meter_summary(arm)
    return {
        "arm": arm,
        "agent_id": agent_id,
        "work": str(work),
        "quality": q,
        "transcript_tokens_est": tr.get("tokens"),
        "transcript": tr,
        "tool_meter": m,
        "tokens_total_est": int(tr.get("tokens") or 0),
    }


def main() -> int:
    # argv: graphify_agent_id d_channel_best_agent_id
    if len(sys.argv) < 3:
        print("usage: score_dev_ab.py <graphify_agent_id> <d_channel_best_agent_id>")
        return 2
    g_id, d_id = sys.argv[1], sys.argv[2]
    results = [score_arm("graphify", g_id), score_arm("d_channel_best", d_id)]
    # winner among feature_ok by lowest transcript tokens
    ok = [r for r in results if r.get("quality", {}).get("feature_ok")]
    pool = ok or results
    winner = sorted(pool, key=lambda r: int(r.get("tokens_total_est") or 10**12))[0]
    report = {
        "mission": json.loads((BASE / "mission.json").read_text(encoding="utf-8")),
        "arms": results,
        "winner_tokens_among_ok": winner["arm"] if ok else None,
        "note": "tokens_total_est = estimate_tokens over full Cursor agent transcript (proxy for tokens exchanged).",
    }
    out = BASE / "report_latest.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "winner": report["winner_tokens_among_ok"],
        "arms": [
            {
                "arm": r["arm"],
                "feature_ok": r["quality"]["feature_ok"],
                "pytest_ok": r["quality"]["pytest_ok"],
                "tokens_total_est": r["tokens_total_est"],
                "tool_tokens_in": r["tool_meter"]["tokens_in"],
                "tool_calls": r["tool_meter"]["calls"],
            }
            for r in results
        ],
        "wrote": str(out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
