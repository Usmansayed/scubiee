"""Session-native CE A/B: TraceLab-naive retrieval vs map/focus/recall/expand.

Deterministic scripted policies (no LLM). Same multi-turn mission, two arms:

  A) baseline_naive  — Grep + full-file reads, re-fetch on every turn (TraceLab-like)
  B) session_native  — map → recall/focus stubs → expand only what we edit

KPI: retrieval payload chars (and estimated tokens) into the "agent context"
     across the whole session. Target: ≥50% reduction for session_native.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\session_native_ab.py
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\session_native_ab.py --repo <path>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.session_store import clear_store, expand, recall  # noqa: E402
from pipeline.token_meter import estimate_tokens  # noqa: E402
from pipeline.work_session import clear_session  # noqa: E402

OUT_DIR = ROOT / "out" / "experiments" / "session_native_ab"

# Prefer small indexed worktrees used elsewhere in CE tests
CANDIDATE_REPOS = [
    ROOT / "testdata" / "cursor_sdk_ab" / "work_d_channel_best_mcponly",
    ROOT / "testdata" / "frontend-mcp",
    ROOT,
]


@dataclass
class TurnMeter:
    turn_id: str
    ops: list[str] = field(default_factory=list)
    payload_chars: int = 0
    payload_tokens: int = 0
    files_touched: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArmResult:
    name: str
    turns: list[TurnMeter] = field(default_factory=list)
    total_chars: int = 0
    total_tokens: int = 0
    ms: float = 0.0
    ok: bool = True
    notes: list[str] = field(default_factory=list)


MISSIONS = [
    {
        "id": "M1_multi_turn_locate",
        "title": "Multi-turn locate -> follow-up -> edit (WF1+WF2+WF5)",
        "turns": [
            {
                "id": "T1_cold_start",
                "query": "shared browser lease busy agent guidance",
                "grep": [r"SharedBrowserLease|shared_lease|busy", r"agent_guidance"],
                "baseline_read_max": 8000,
            },
            {
                "id": "T2_follow_up",
                "query": "where is busy lease guidance emitted",
                "grep": [r"busy|guidance|lease"],
                "baseline_read_max": 8000,
                "prefer_memory": True,
            },
            {
                "id": "T3_edit_expand",
                "query": "expand the primary lease module for editing",
                "grep": [r"class SharedBrowserLease|def ", r"lease"],
                "baseline_read_max": 8000,
                "prefer_memory": True,
                "expand_for_edit": True,
            },
        ],
    },
    {
        "id": "M2_repair_style",
        "title": "Cold map then repair-style re-focus (WF1+WF3)",
        "turns": [
            {
                "id": "T1_map",
                "query": "session runtime store persistence",
                "grep": [r"session|runtime|store", r"persist"],
                "baseline_read_max": 6000,
            },
            {
                "id": "T2_repair",
                "query": "fix error path in session store",
                "grep": [r"error|store|session"],
                "baseline_read_max": 6000,
                "prefer_memory": True,
                "expand_for_edit": True,
            },
        ],
    },
]


def _ensure_engine(repo: Path) -> dict[str, Any]:
    """Warm CE daemon for this repo; abort if search still returns no hits."""
    os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
    os.environ["CTX_REPO"] = str(repo)
    try:
        from pipeline.daemon import ensure_daemon

        info = ensure_daemon(repo=repo) or {}
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"engine ensure failed: {exc}\nRun: python -m pipeline engine ensure"
        ) from exc

    # Probe: empty map targets = false-positive savings (seen when daemon down)
    from pipeline.locate import locate
    from pipeline.session_store import clear_store
    from pipeline.work_session import clear_session

    clear_session(repo)
    clear_store(repo)
    probe = locate("shared browser lease", repo=repo, mode="map")
    n = len(probe.get("targets") or [])
    if n < 1:
        raise SystemExit(
            "locate map returned 0 targets after engine ensure — index/search unusable. "
            "Refusing to report savings (would be inflated)."
        )
    print(f"engine ok url={os.environ.get('CTX_ENGINE_URL')} probe_targets={n}")
    return {"ensure": info, "probe_targets": n}


def _pick_repo(explicit: Path | None) -> Path:
    if explicit and explicit.is_dir():
        return explicit.resolve()
    for p in CANDIDATE_REPOS:
        if p.is_dir():
            return p.resolve()
    return ROOT.resolve()


def _add_payload(turn: TurnMeter, text: str, op: str) -> None:
    turn.ops.append(op)
    ch = len(text or "")
    turn.payload_chars += ch
    turn.payload_tokens += estimate_tokens(text or "")


def _ripgrep(repo: Path, pattern: str, max_hits: int = 40) -> list[dict[str, Any]]:
    """Best-effort content search without shelling out if possible."""
    hits: list[dict[str, Any]] = []
    cre = re.compile(pattern, re.I)
    skip = {".git", ".venv", "node_modules", ".context-engine", "__pycache__", "out"}
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith((".py", ".ts", ".tsx", ".js", ".md")):
                continue
            fp = Path(dirpath) / fn
            try:
                rel = fp.relative_to(repo).as_posix()
            except ValueError:
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if cre.search(text):
                hits.append({"file": rel, "chars": len(text)})
                if len(hits) >= max_hits:
                    return hits
    return hits


def _read_file(repo: Path, rel: str, max_chars: int) -> str:
    try:
        text = (repo / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + "\n…[truncated]"
    return text


def run_baseline(repo: Path, mission: dict[str, Any]) -> ArmResult:
    """TraceLab-like: grep + full(ish) file reads every turn, including re-reads."""
    arm = ArmResult(name="baseline_naive")
    t0 = time.time()
    seen_files: list[str] = []

    for turn_spec in mission["turns"]:
        tm = TurnMeter(turn_id=turn_spec["id"])
        # orient-ish listing cost (cheap proxy for ls)
        listing = "\n".join(
            p.as_posix()
            for p in sorted(repo.rglob("*.py"))[:80]
            if ".venv" not in p.parts and "node_modules" not in p.parts
        )
        _add_payload(tm, listing, "orient_ls_proxy")

        files: list[str] = []
        for pat in turn_spec.get("grep") or []:
            hits = _ripgrep(repo, pat, max_hits=25)
            # grep result dump (paths + match density proxy)
            dump = json.dumps(
                [{"file": h["file"], "file_chars": h["chars"]} for h in hits],
                ensure_ascii=False,
            )
            _add_payload(tm, dump, f"grep:{pat[:40]}")
            for h in hits:
                if h["file"] not in files:
                    files.append(h["file"])

        # Always re-read top files (duplicate tax on follow-ups)
        max_read = int(turn_spec.get("baseline_read_max") or 8000)
        for rel in files[:6]:
            body = _read_file(repo, rel, max_read)
            _add_payload(tm, body, f"read:{rel}")
            if rel not in tm.files_touched:
                tm.files_touched.append(rel)
            if rel not in seen_files:
                seen_files.append(rel)

        tm.detail = {"n_files": len(tm.files_touched), "grep_patterns": turn_spec.get("grep")}
        arm.turns.append(tm)
        arm.total_chars += tm.payload_chars
        arm.total_tokens += tm.payload_tokens

    arm.ms = round((time.time() - t0) * 1000, 1)
    arm.notes.append(f"unique_files_session={len(seen_files)}")
    return arm


def run_session_native(repo: Path, mission: dict[str, Any]) -> ArmResult:
    """CE playbook: map once, recall/focus on follow-ups, expand only for edit."""
    from pipeline.locate import locate
    from pipeline.work_session import pin, touch

    arm = ArmResult(name="session_native")
    t0 = time.time()
    clear_session(repo)
    clear_store(repo)
    os.environ["CTX_REPO"] = str(repo)
    os.environ["CTX_TOKEN_MODE"] = "savings"
    os.environ["CTX_SESSION_GOVERNOR"] = "1"
    os.environ.setdefault("CTX_RETRIEVE", "D")

    primary_handle: str | None = None
    primary_file: str | None = None

    for i, turn_spec in enumerate(mission["turns"]):
        tm = TurnMeter(turn_id=turn_spec["id"])
        q = turn_spec["query"]
        try:
            if i == 0 or not turn_spec.get("prefer_memory"):
                card = locate(q, repo=repo, mode="map")
                payload = json.dumps(card, default=str)
                _add_payload(tm, payload, "map")
                targets = card.get("targets") or []
                if targets:
                    primary_handle = targets[0].get("handle")
                    primary_file = targets[0].get("file")
                    tm.files_touched = [t.get("file") for t in targets if t.get("file")]
                    if primary_file:
                        try:
                            pin(repo, primary_file)
                            touch(repo, [primary_file], query=q, weight=2)
                        except Exception:  # noqa: BLE001
                            pass
                tm.detail = {
                    "handles": [t.get("handle") for t in targets],
                    "already_in_session": sum(
                        1 for t in targets if t.get("status") == "already_in_session"
                    ),
                    "token_estimate": card.get("token_estimate"),
                }
            else:
                # follow-up: recall first
                mem = recall(repo, need=q, top_n=15)
                _add_payload(tm, json.dumps(mem, default=str), "recall")
                # focus for new need
                foc = locate(q, repo=repo, mode="focus")
                _add_payload(tm, json.dumps(foc, default=str), "focus")
                targets = foc.get("targets") or []
                tm.files_touched = [t.get("file") for t in targets if t.get("file")]
                stubs = sum(1 for t in targets if t.get("status") == "already_in_session")
                if not primary_handle and targets:
                    primary_handle = targets[0].get("handle")
                    primary_file = targets[0].get("file")
                tm.detail = {
                    "recall_spans": len(mem.get("spans") or []),
                    "focus_already_in_session": stubs,
                    "handles": [t.get("handle") for t in targets],
                }

            if turn_spec.get("expand_for_edit"):
                hid = primary_handle
                if not hid:
                    # last resort from recall
                    mem2 = recall(repo, need="", top_n=5)
                    spans = mem2.get("spans") or []
                    if spans:
                        hid = spans[0].get("handle")
                if hid:
                    body = expand(repo, hid, max_chars=4000)
                    _add_payload(tm, json.dumps(body, default=str), f"expand:{hid}")
                    tm.detail["expanded"] = hid
                else:
                    arm.notes.append(f"{turn_spec['id']}: no handle to expand")
        except Exception as exc:  # noqa: BLE001
            arm.ok = False
            arm.notes.append(f"{turn_spec['id']}: {exc}")
            _add_payload(tm, f"ERROR {exc}", "error")

        arm.turns.append(tm)
        arm.total_chars += tm.payload_chars
        arm.total_tokens += tm.payload_tokens

    arm.ms = round((time.time() - t0) * 1000, 1)
    return arm


def summarize(baseline: ArmResult, ce: ArmResult) -> dict[str, Any]:
    b_ch, c_ch = baseline.total_chars, ce.total_chars
    b_tok, c_tok = baseline.total_tokens, ce.total_tokens
    sav_ch = (1.0 - (c_ch / b_ch)) if b_ch else 0.0
    sav_tok = (1.0 - (c_tok / b_tok)) if b_tok else 0.0
    return {
        "baseline_chars": b_ch,
        "ce_chars": c_ch,
        "baseline_tokens": b_tok,
        "ce_tokens": c_tok,
        "savings_chars_frac": round(sav_ch, 4),
        "savings_tokens_frac": round(sav_tok, 4),
        "hit_50pct_chars": sav_ch >= 0.5,
        "hit_50pct_tokens": sav_tok >= 0.5,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Session-native CE vs TraceLab-naive A/B")
    ap.add_argument("--repo", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    repo = _pick_repo(args.repo)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("CTX_REPO", str(repo))
    engine_meta = _ensure_engine(repo)
    results = {
        "repo": str(repo),
        "kpi": "retrieval_payload_chars_and_tokens",
        "target_savings": 0.5,
        "engine": engine_meta,
        "missions": [],
    }

    print(f"repo={repo}")
    for mission in MISSIONS:
        print(f"\n=== {mission['id']}: {mission['title']} ===")
        base = run_baseline(repo, mission)
        ce = run_session_native(repo, mission)
        summary = summarize(base, ce)
        print(
            f"  baseline chars={base.total_chars} tok≈{base.total_tokens} ({base.ms}ms)"
        )
        print(f"  CE       chars={ce.total_chars} tok≈{ce.total_tokens} ({ce.ms}ms) ok={ce.ok}")
        print(
            f"  savings  chars={summary['savings_chars_frac']*100:.1f}% "
            f"tokens={summary['savings_tokens_frac']*100:.1f}% "
            f"hit50={summary['hit_50pct_chars']}"
        )
        if ce.notes:
            print(f"  notes: {ce.notes}")
        results["missions"].append(
            {
                "mission": mission,
                "baseline": asdict(base),
                "session_native": asdict(ce),
                "summary": summary,
            }
        )

    # aggregate
    b_sum = sum(m["baseline"]["total_chars"] for m in results["missions"])
    c_sum = sum(m["session_native"]["total_chars"] for m in results["missions"])
    b_tok = sum(m["baseline"]["total_tokens"] for m in results["missions"])
    c_tok = sum(m["session_native"]["total_tokens"] for m in results["missions"])
    agg = {
        "baseline_chars": b_sum,
        "ce_chars": c_sum,
        "baseline_tokens": b_tok,
        "ce_tokens": c_tok,
        "savings_chars_frac": round(1 - c_sum / b_sum, 4) if b_sum else 0,
        "savings_tokens_frac": round(1 - c_tok / b_tok, 4) if b_tok else 0,
    }
    agg["hit_50pct_chars"] = agg["savings_chars_frac"] >= 0.5
    results["aggregate"] = agg

    json_path = out / "results.json"
    json_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    md = [
        "# Session-native CE A/B results",
        "",
        f"**Repo:** `{repo}`  ",
        f"**KPI:** retrieval payload chars/tokens across scripted multi-turn missions  ",
        f"**Target:** ≥50% savings vs TraceLab-naive (grep + re-read)  ",
        "",
        "## Aggregate",
        "",
        f"| Arm | Chars | Tokens |",
        f"|---|---:|---:|",
        f"| baseline_naive | {b_sum} | {b_tok} |",
        f"| session_native | {c_sum} | {c_tok} |",
        f"| **savings** | **{agg['savings_chars_frac']*100:.1f}%** | **{agg['savings_tokens_frac']*100:.1f}%** |",
        "",
        f"Hit 50% (chars): **{agg['hit_50pct_chars']}**",
        "",
        "## Per mission",
        "",
    ]
    for m in results["missions"]:
        s = m["summary"]
        md.append(f"### {m['mission']['id']}")
        md.append(
            f"- baseline: {m['baseline']['total_chars']} chars / {m['baseline']['total_tokens']} tok"
        )
        md.append(
            f"- CE: {m['session_native']['total_chars']} chars / {m['session_native']['total_tokens']} tok"
        )
        md.append(
            f"- savings: {s['savings_chars_frac']*100:.1f}% chars, "
            f"{s['savings_tokens_frac']*100:.1f}% tokens (hit50={s['hit_50pct_chars']})"
        )
        md.append("")

    md.append("## Method notes")
    md.append("")
    md.append(
        "- Deterministic policies (no LLM). Baseline re-greps and re-reads every turn."
    )
    md.append(
        "- CE uses map once, then recall+focus; expand only on edit turns."
    )
    md.append(
        "- This measures **tool payload** into context — the TraceLab append tax."
    )
    md.append(
        "- Harness refuses to run if map returns 0 targets (empty search inflates savings)."
    )
    md.append(
        "- Not a live-agent proof: assumes agents follow map/recall/focus/expand "
        "(no Grep/Bash discovery)."
    )
    md_path = out / "REPORT.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nwrote {json_path}")
    print(f"wrote {md_path}")
    print(
        f"AGGREGATE savings chars={agg['savings_chars_frac']*100:.1f}% "
        f"tokens={agg['savings_tokens_frac']*100:.1f}% hit50={agg['hit_50pct_chars']}"
    )


if __name__ == "__main__":
    main()
