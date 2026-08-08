"""Score Cursor SDK A/B work folders after agents finish."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "out" / "experiments" / "cursor_sdk_ab"
WORK_BASE = ROOT / "testdata" / "cursor_sdk_ab"
MISSION = json.loads((Path(__file__).parent / "mission.json").read_text(encoding="utf-8"))


def score_arm(arm: str) -> dict:
    work = WORK_BASE / (
        "work_graphify_mcponly" if arm == "graphify" else "work_d_channel_best_mcponly"
    )
    result_path = OUT / f"result_{arm}.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}

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

    test_files = list(work.rglob("*busy*.py")) + list(work.rglob("*contention*.py"))
    test_files = [p for p in test_files if "test" in p.name.lower()]

    pytest_ok = False
    pytest_out = ""
    if test_files:
        rel = str(test_files[0].relative_to(work))
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", rel, "-q"],
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=120,
        )
        pytest_ok = proc.returncode == 0
        pytest_out = ((proc.stdout or "") + (proc.stderr or ""))[-800:]

    feature_ok = any(
        h.get("has_busy") and h.get("has_contention_hint") for h in guidance_hits
    )
    usage = (result.get("usage") or {}) if isinstance(result, dict) else {}
    return {
        "arm": arm,
        "feature_ok": feature_ok,
        "pytest_ok": pytest_ok,
        "pytest_out": pytest_out,
        "guidance_hits": guidance_hits,
        "test_files": [str(p.relative_to(work)).replace("\\", "/") for p in test_files],
        "status": result.get("status"),
        "totalTokens": usage.get("totalTokens"),
        "usage": usage,
        "elapsed_ms": result.get("elapsed_ms"),
        "agentId": result.get("agentId"),
    }


def main() -> int:
    rows = [score_arm(a) for a in MISSION["arms"]]
    quality = [r for r in rows if r["feature_ok"] and r.get("status") == "finished"]
    pool = quality or [r for r in rows if r.get("totalTokens") is not None]
    winner = None
    if pool:
        winner = sorted(pool, key=lambda r: int(r.get("totalTokens") or 10**12))[0]["arm"]
    report = {
        "metric": "usage.totalTokens (Cursor SDK)",
        "prompt": MISSION["prompt"],
        "arms": rows,
        "verdict": {
            "quality_pass": {r["arm"]: bool(r["feature_ok"]) for r in rows},
            "pytest_pass": {r["arm"]: bool(r["pytest_ok"]) for r in rows},
            "token_winner_among_quality": winner,
            "tokens": {r["arm"]: r.get("totalTokens") for r in rows},
        },
    }
    out = OUT / "score_latest.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
