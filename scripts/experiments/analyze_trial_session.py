"""Analyze ce_read vs raw trial sessions for MCP ROI and usage patterns."""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRIAL_ROOT = Path(r"C:\Users\usman\AppData\Local\Temp\ce_dev_trial")

# Focus: CE-first instruction runs + one pre-CE-first baseline.
RUNS = [
    ("pre_ce_first (+6%)", "20260809T165457Z"),
    ("thrash", "20260809T175225Z"),
    ("degraded", "20260809T182513Z"),
    ("consistency", "20260809T183806Z"),
]


def _result_chars(res: object) -> int:
    if res is None:
        return 0
    if isinstance(res, str):
        return len(res)
    return len(json.dumps(res, ensure_ascii=False, default=str))


def parse_conversation(run: Path, arm: str) -> dict:
    path = run / f"{arm}-conversation.json"
    if not path.is_file():
        return {}
    conv = json.loads(path.read_text(encoding="utf-8"))
    steps = conv[0]["turn"]["steps"]
    tool_seq: list[str] = []
    mcp_calls: list[dict] = []
    native_locate: list[dict] = []
    first_mcp_idx = None
    first_grep_idx = None
    first_search_mcp_idx = None

    for i, s in enumerate(steps):
        if s.get("type") != "toolCall":
            continue
        m = s.get("message") or {}
        t = m.get("type") or ""
        tool_seq.append(t)
        if t == "mcp":
            args = m.get("args") or {}
            tool_name = args.get("toolName") or "?"
            inner = args.get("args") or {}
            chars = _result_chars(m.get("result"))
            try:
                body = m["result"]["value"]["content"][0]["text"]["text"]
                content_chars = len(body)
            except (KeyError, IndexError, TypeError):
                content_chars = chars
            mcp_calls.append(
                {
                    "tool": tool_name,
                    "args": inner,
                    "content_chars": content_chars,
                }
            )
            if first_mcp_idx is None:
                first_mcp_idx = i
            if tool_name == "search" and first_search_mcp_idx is None:
                first_search_mcp_idx = i
        elif t == "grep":
            if first_grep_idx is None:
                first_grep_idx = i
            native_locate.append(
                {"name": "grep", "chars": _result_chars(m.get("result")), "args": m.get("args")}
            )
        elif t in {"read", "glob"}:
            native_locate.append(
                {"name": t, "chars": _result_chars(m.get("result")), "args": m.get("args")}
            )

    # Dedupe MCP by (tool, json args)
    seen: set[str] = set()
    uniq_mcp: list[dict] = []
    for c in mcp_calls:
        key = json.dumps({"t": c["tool"], "a": c["args"]}, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        uniq_mcp.append(c)

    locate_native_chars = sum(x["chars"] for x in native_locate)
    mcp_content_chars = sum(c["content_chars"] for c in uniq_mcp)

    return {
        "tool_calls_total": len([s for s in steps if s.get("type") == "toolCall"]),
        "first_tools": tool_seq[:12],
        "first_mcp_step": first_mcp_idx,
        "first_grep_step": first_grep_idx,
        "first_search_mcp_step": first_search_mcp_idx,
        "mcp_stream_n": len(mcp_calls),
        "mcp_unique_n": len(uniq_mcp),
        "mcp_unique": collections.Counter(c["tool"] for c in uniq_mcp),
        "mcp_content_chars": mcp_content_chars,
        "native_locate_n": len(native_locate),
        "native_locate_chars": locate_native_chars,
        "mcp_share_locate_payload": (
            100 * mcp_content_chars / max(1, mcp_content_chars + locate_native_chars)
        ),
        "uniq_mcp_detail": uniq_mcp[:8],
    }


def load_arm(run: Path, arm: str) -> dict:
    return json.loads((run / f"{arm}-arm.json").read_text(encoding="utf-8"))


def analyze_run(label: str, ts: str) -> dict:
    run = TRIAL_ROOT / ts
    data = json.loads((run / "results.json").read_text(encoding="utf-8"))
    out: dict = {
        "label": label,
        "ts": ts,
        "prompt_id": data.get("prompt_id", "thrash/legacy"),
    }
    for arm in ("ce_read", "raw"):
        a = load_arm(run, arm)
        u = a.get("usage") or {}
        nat = collections.Counter(a.get("native_tool_names") or [])
        mcp = collections.Counter(a.get("mcp_call_names") or {})
        inp, out_t = u.get("input_tokens") or 0, u.get("output_tokens") or 0
        conv = parse_conversation(run, arm) if arm == "ce_read" else {}
        out[arm] = {
            "status": a.get("status"),
            "work_complete": a.get("work_complete"),
            "quality_pass": a.get("quality_pass"),
            "implementation_present": a.get("implementation_present"),
            "new_test_files": a.get("new_test_files") or [],
            "source_files_n": len(a.get("source_files_changed") or []),
            "work_tokens": inp + out_t,
            "mcp_stream": dict(mcp),
            "mcp_stream_n": sum(mcp.values()),
            "nread": nat.get("read", 0),
            "ngrep": nat.get("grep", 0),
            "nglob": nat.get("glob", 0),
            "conversation": conv,
        }
    ce, rw = out["ce_read"], out["raw"]
    if rw["work_tokens"]:
        out["delta_work_pct"] = (ce["work_tokens"] - rw["work_tokens"]) / rw["work_tokens"] * 100
    out["delta_nread"] = ce["nread"] - rw["nread"]
    out["delta_ngrep"] = ce["ngrep"] - rw["ngrep"]
    out["fair_complete"] = ce["work_complete"] and rw["work_complete"]
    out["roi_signal"] = (
        out.get("fair_complete")
        and out.get("delta_work_pct", 0) < 0
        and out.get("delta_nread", 0) <= 0
    )
    return out


def main() -> int:
    rows = [analyze_run(label, ts) for label, ts in RUNS]
    print("=" * 72)
    print("MCP SESSION ROI ANALYSIS (ce_read vs raw)")
    print("=" * 72)
    for r in rows:
        print(f"\n## {r['label']} ({r['ts']}) prompt_id={r['prompt_id']}")
        ce, rw = r["ce_read"], r["raw"]
        print(
            f"  work: CE {ce['work_tokens']:,} | raw {rw['work_tokens']:,} "
            f"| delta {r.get('delta_work_pct', 0):+.1f}%"
        )
        print(
            f"  complete: CE {ce['work_complete']} | raw {rw['work_complete']} "
            f"| fair={r['fair_complete']} | roi_signal={r['roi_signal']}"
        )
        print(
            f"  native: reads CE {ce['nread']} raw {rw['nread']} ({r['delta_nread']:+d}) | "
            f"greps CE {ce['ngrep']} raw {rw['ngrep']} ({r['delta_ngrep']:+d})"
        )
        print(
            f"  CE MCP stream={ce['mcp_stream_n']} {ce['mcp_stream']} | "
            f"impl={ce['implementation_present']} new_tests={len(ce['new_test_files'])}"
        )
        c = ce.get("conversation") or {}
        if c:
            print(f"  CE first tools: {c.get('first_tools', [])}")
            print(
                f"  CE MCP unique={c.get('mcp_unique_n')} {dict(c.get('mcp_unique', {}))} | "
                f"locate payload share={c.get('mcp_share_locate_payload', 0):.1f}%"
            )
            print(
                f"  first step: grep={c.get('first_grep_step')} "
                f"search_mcp={c.get('first_search_mcp_step')} "
                f"any_mcp={c.get('first_mcp_step')}"
            )
            for i, call in enumerate(c.get("uniq_mcp_detail") or [], 1):
                a = json.dumps(call["args"], ensure_ascii=False)[:100]
                print(f"    mcp{i}: {call['tool']} ~{call['content_chars']//4}tok {a}")

    # Summary verdict
    fair_wins = sum(1 for r in rows if r["roi_signal"])
    token_wins_any = sum(1 for r in rows if r.get("delta_work_pct", 0) < 0)
    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)
    print(f"Runs analyzed: {len(rows)}")
    print(f"Fair ROI wins (complete + cheaper + reads not worse): {fair_wins}/{len(rows)}")
    print(f"Token wins (any completion state): {token_wins_any}/{len(rows)}")
    pre = rows[0]
    post = rows[1:]
    post_fair = [r for r in post if r["fair_complete"]]
    if post_fair:
        avg_delta = sum(r["delta_work_pct"] for r in post_fair) / len(post_fair)
        avg_dread = sum(r["delta_nread"] for r in post_fair) / len(post_fair)
        print(f"CE-first fair runs avg token delta: {avg_delta:+.1f}%")
        print(f"CE-first fair runs avg native-read delta: {avg_dread:+.1f}")
    print(
        f"Pre CE-first ({pre['label']}): delta {pre.get('delta_work_pct', 0):+.1f}%, "
        f"reads {pre['delta_nread']:+d}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
