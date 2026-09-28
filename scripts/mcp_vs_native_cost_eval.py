"""Compare time + tokens: Scubiee MCP ladder vs native Grep/Read exploration.

Same problems. Metrics:
  - wall_ms
  - out_chars / out_tokens (~chars/4)
  - tool_calls
  - file_rec / symbol_rec vs gold (quality check)

Paths:
  mcp_lean   — soft map + pack_context(mode=lean)  [what GATE recommends]
  mcp_full   — soft map + pack_context(mode=full)
  native     — keyword ripgrep + read matching files (typical explore thrash)
  native_gold— read gold files only (oracle lower bound for native)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"C:/Users/usman/Downloads/context-engine")
OUT = Path("docs/superpowers/plans/2026-09-05-mcp-vs-native-cost.json")
OUT_MD = Path("docs/superpowers/plans/2026-09-05-mcp-vs-native-cost.md")

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "packages"))

from ten_problem_map_pack_eval import PROBLEMS, _pick_seed, _score_pack, _soft_map  # noqa: E402


def _tokens(chars: int) -> int:
    return max(0, (chars + 3) // 4)


def _json_chars(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str))


def _score_files_syms(
    files: set[str], syms: set[str], gold_files: list[str], gold_symbols: list[str]
) -> dict[str, Any]:
    files_n = {f.replace("\\", "/") for f in files}
    fh = sum(1 for g in gold_files if any(f.endswith(g) or g in f for f in files_n))
    sh = sum(1 for g in gold_symbols if g in syms or any(s.endswith(g) or g in s for s in syms))
    return {
        "file_rec": round(fh / len(gold_files), 3) if gold_files else None,
        "symbol_rec": round(sh / len(gold_symbols), 3) if gold_symbols else None,
    }


_STOP = frozenset(
    "a an the to for of in on and or how does when from with that this into via".split()
)


def _keywords(text: str, *, limit: int = 8) -> list[str]:
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_\.]{2,}", text)
    out: list[str] = []
    seen: set[str] = set()
    for t in toks:
        tl = t.lower()
        if tl in _STOP or tl in seen:
            continue
        seen.add(tl)
        out.append(t)
        if len(out) >= limit:
            break
    return out


def _rg(pattern: str, *, glob: str = "*.py", max_hits: int = 40) -> tuple[str, int, float]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [
                "rg",
                "-n",
                "--no-heading",
                "-g",
                glob,
                "-g",
                "!**/node_modules/**",
                "-g",
                "!**/.git/**",
                "-g",
                "!**/__pycache__/**",
                "-m",
                "20",
                pattern,
                str(ROOT),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        lines = (proc.stdout or "").splitlines()[:max_hits]
        body = "\n".join(lines)
        return body, len(body), (time.perf_counter() - t0) * 1000
    except FileNotFoundError:
        # fallback: python walk + regex (slower)
        hits: list[str] = []
        rx = re.compile(re.escape(pattern), re.I)
        for p in ROOT.rglob(glob.replace("*", "")) if False else ROOT.rglob("*.py"):
            rel = str(p.relative_to(ROOT)).replace("\\", "/")
            if any(x in rel for x in (".git/", "__pycache__", "node_modules", ".venv")):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{i}:{line[:200]}")
                    if len(hits) >= max_hits:
                        body = "\n".join(hits)
                        return body, len(body), (time.perf_counter() - t0) * 1000
        body = "\n".join(hits)
        return body, len(body), (time.perf_counter() - t0) * 1000
    except subprocess.TimeoutExpired:
        return "", 0, (time.perf_counter() - t0) * 1000


def run_native(prob: dict[str, Any]) -> dict[str, Any]:
    """Typical explore: keyword rg + read files that appear in hits."""
    t0 = time.perf_counter()
    keys = _keywords(prob["map_query"] + " " + " ".join(prob.get("gold_symbols") or []))
    blobs: list[str] = []
    tool_calls = 0
    hit_files: set[str] = set()
    rg_ms = 0.0
    for kw in keys:
        body, n, ms = _rg(kw)
        tool_calls += 1
        rg_ms += ms
        blobs.append(body)
        for line in body.splitlines():
            if ":" in line:
                hit_files.add(line.split(":", 1)[0].replace("\\", "/"))

    # Read up to 6 hit files (agent would open several)
    read_chars = 0
    read_ms = 0.0
    syms: set[str] = set()
    files_read: set[str] = set()
    for rel in sorted(hit_files)[:6]:
        p = ROOT / rel
        if not p.is_file():
            continue
        t1 = time.perf_counter()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Cap per-file like a generous Read (first 400 lines)
        lines = text.splitlines()[:400]
        chunk = "\n".join(lines)
        read_chars += len(chunk)
        read_ms += (time.perf_counter() - t1) * 1000
        tool_calls += 1
        files_read.add(rel)
        for m in re.finditer(r"^\s*(?:def|class|async def)\s+([A-Za-z_][\w\.]*)", chunk, re.M):
            syms.add(m.group(1))

    out_chars = sum(len(b) for b in blobs) + read_chars
    score = _score_files_syms(files_read | hit_files, syms, prob["gold_files"], prob.get("gold_symbols") or [])
    return {
        "path": "native",
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        "rg_ms": round(rg_ms, 1),
        "read_ms": round(read_ms, 1),
        "tool_calls": tool_calls,
        "out_chars": out_chars,
        "out_tokens": _tokens(out_chars),
        "keywords": keys,
        "files_touched": sorted(files_read | hit_files)[:20],
        "n_files_touched": len(files_read | hit_files),
        **score,
    }


def run_native_gold(prob: dict[str, Any]) -> dict[str, Any]:
    """Oracle native: only read gold files (best-case without search thrash)."""
    t0 = time.perf_counter()
    out_chars = 0
    files: set[str] = set()
    syms: set[str] = set()
    for rel in prob["gold_files"]:
        p = ROOT / rel
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        chunk = "\n".join(text.splitlines()[:400])
        out_chars += len(chunk)
        files.add(rel.replace("\\", "/"))
        for m in re.finditer(r"^\s*(?:def|class|async def)\s+([A-Za-z_][\w\.]*)", chunk, re.M):
            syms.add(m.group(1))
    score = _score_files_syms(files, syms, prob["gold_files"], prob.get("gold_symbols") or [])
    return {
        "path": "native_gold",
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        "tool_calls": len(prob["gold_files"]),
        "out_chars": out_chars,
        "out_tokens": _tokens(out_chars),
        "n_files_touched": len(files),
        **score,
    }


def run_mcp(prob: dict[str, Any], *, mode: str) -> dict[str, Any]:
    from pipeline.context_trace import _CACHE, run_expand_context, run_pack_context

    t0 = time.perf_counter()
    tool_calls = 0
    payloads: list[Any] = []

    map_out = _soft_map(ROOT, prob["map_query"], k=10)
    tool_calls += 1
    payloads.append(map_out)
    cards = list(map_out.get("cards") or [])
    seed_card = _pick_seed(cards, prob["gold_files"])
    if seed_card.get("file"):
        seed_file = seed_card["file"]
        seed_symbol = seed_card.get("symbol") or ""
        seed_line = int(seed_card.get("start_line") or 0)
        seed_source = "map"
    else:
        seed_file = prob["gold_files"][0]
        seed_symbol = (prob.get("gold_symbols") or [""])[0]
        seed_line = 0
        seed_source = "gold_fallback"

    kwargs: dict[str, Any] = {
        "seed_file": seed_file,
        "mode": mode,
        "policy": "strict",
        "k": 16,
        "hot_threshold": 0.65,
        "drop_noise": True,
    }
    if seed_symbol and "(" not in seed_symbol:
        kwargs["seed_symbol"] = seed_symbol
    elif seed_line:
        kwargs["seed_line"] = seed_line

    pack = run_pack_context(ROOT, prob["pack_query"], **kwargs)
    tool_calls += 1
    payloads.append(pack)
    if not pack.get("ok"):
        pack = run_pack_context(
            ROOT,
            prob["pack_query"],
            seed_file=prob["gold_files"][0],
            seed_symbol=(prob.get("gold_symbols") or [""])[0],
            mode=mode,
        )
        tool_calls += 1
        payloads.append(pack)
        seed_source = "gold_retry"

    expand = None
    if mode == "lean" and pack.get("ok"):
        sid = (pack.get("seed") or {}).get("id") or ""
        if sid:
            prior = {c.get("id") for c in (pack.get("heatmap") or []) if c.get("id")}
            prior_packed = {b.get("id") for b in (pack.get("pack") or []) if b.get("id")}
            expand = run_expand_context(
                ROOT,
                sid,
                query=prob["pack_query"],
                direction="callees",
                with_bodies=True,
                k=8,
                prior_ids=prior,
                prior_packed_ids=prior_packed,
            )
            tool_calls += 1
            payloads.append(expand)

    out_chars = sum(_json_chars(p) for p in payloads if p is not None)
    # Prefer declared pack chars + slim card overhead when available
    declared = int(pack.get("chars") or 0) if pack.get("ok") else 0
    if expand and expand.get("ok"):
        declared += int(expand.get("chars") or 0)

    score = (
        _score_pack(pack, prob["gold_files"], prob.get("gold_symbols") or [])
        if pack.get("ok")
        else {"file_rec": 0.0, "symbol_rec": 0.0}
    )
    # Union expand into score lightly
    files = set(score.get("files") or [])
    # recompute from pack+expand
    files = set()
    syms = set()
    for part in (pack, expand or {}):
        for b in (part.get("pack") or []) + (part.get("heatmap") or []) + (part.get("delta") or []):
            if b.get("file"):
                files.add(str(b["file"]).replace("\\", "/"))
            if b.get("symbol"):
                syms.add(str(b["symbol"]))
    score2 = _score_files_syms(files, syms, prob["gold_files"], prob.get("gold_symbols") or [])

    return {
        "path": f"mcp_{mode}",
        "wall_ms": round((time.perf_counter() - t0) * 1000, 1),
        "tool_calls": tool_calls,
        "out_chars": out_chars,
        "out_tokens": _tokens(out_chars),
        "body_chars_declared": declared,
        "body_tokens_declared": _tokens(declared),
        "seed_source": seed_source,
        "seed_file": seed_file,
        "engine": pack.get("engine") if pack else None,
        "packed": pack.get("packed") if pack else None,
        "heatmap_n": pack.get("count") if pack else None,
        "expand_delta": (expand or {}).get("count"),
        "file_rec": score2["file_rec"],
        "symbol_rec": score2["symbol_rec"],
        "pack_only_file_rec": score.get("file_rec"),
        "pack_only_symbol_rec": score.get("symbol_rec"),
    }


def run() -> dict[str, Any]:
    os.environ.setdefault("CTX_TRACE_ENGINE", "composite_v1")
    from pipeline.context_trace import _CACHE

    _CACHE.clear()
    # Warm once so first-problem compile doesn't dominate unfairly
    t_warm = time.perf_counter()
    _soft_map(ROOT, "warmup scubiee context_trace", k=3)
    warm_ms = round((time.perf_counter() - t_warm) * 1000, 1)

    rows: list[dict[str, Any]] = []
    # Use first 5 problems for a focused cost bakeoff
    problems = PROBLEMS[:5]
    for prob in problems:
        print(f"=== {prob['id']} ===")
        native = run_native(prob)
        print(f"  native      {native['wall_ms']:7.0f}ms  {native['out_tokens']:6d} tok  calls={native['tool_calls']}  file={native['file_rec']}")
        gold = run_native_gold(prob)
        print(f"  native_gold {gold['wall_ms']:7.0f}ms  {gold['out_tokens']:6d} tok  calls={gold['tool_calls']}  file={gold['file_rec']}")
        lean = run_mcp(prob, mode="lean")
        print(f"  mcp_lean    {lean['wall_ms']:7.0f}ms  {lean['out_tokens']:6d} tok  body={lean.get('body_tokens_declared')}  file={lean['file_rec']} eng={lean.get('engine')}")
        full = run_mcp(prob, mode="full")
        print(f"  mcp_full    {full['wall_ms']:7.0f}ms  {full['out_tokens']:6d} tok  body={full.get('body_tokens_declared')}  file={full['file_rec']}")
        rows.append({"id": prob["id"], "problem": prob["problem"], "native": native, "native_gold": gold, "mcp_lean": lean, "mcp_full": full})

    def mean(path: str, key: str) -> float:
        vals = [r[path][key] for r in rows if r[path].get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    summary = {
        "warm_ms": warm_ms,
        "n": len(rows),
        "means": {
            p: {
                "wall_ms": mean(p, "wall_ms"),
                "out_tokens": mean(p, "out_tokens"),
                "tool_calls": mean(p, "tool_calls"),
                "file_rec": mean(p, "file_rec"),
                "symbol_rec": mean(p, "symbol_rec"),
            }
            for p in ("native", "native_gold", "mcp_lean", "mcp_full")
        },
    }
    # ratios
    nt = summary["means"]["native"]["out_tokens"] or 1
    summary["token_ratio_native_over_mcp_lean"] = round(nt / max(1, summary["means"]["mcp_lean"]["out_tokens"]), 2)
    summary["time_ratio_native_over_mcp_lean"] = round(
        (summary["means"]["native"]["wall_ms"] or 1) / max(1, summary["means"]["mcp_lean"]["wall_ms"]), 2
    )

    report = {
        "ok": True,
        "protocol": "same 5 problems; mcp uses composite_v1; native=rg+read hits; native_gold=read gold files",
        "token_estimate": "chars/4",
        "summary": summary,
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    m = summary["means"]
    md = f"""# MCP vs native cost (time + tokens)

**n={summary['n']}** problems from ten-problem set. Engine: `composite_v1`.
Token estimate: `chars/4`. Warmup compile: **{warm_ms} ms** (excluded from per-problem means).

| Path | mean wall ms | mean out tokens | mean tool calls | mean file_rec |
|------|-------------:|----------------:|----------------:|--------------:|
| native (rg+read) | {m['native']['wall_ms']} | {m['native']['out_tokens']} | {m['native']['tool_calls']} | {m['native']['file_rec']} |
| native_gold (oracle read) | {m['native_gold']['wall_ms']} | {m['native_gold']['out_tokens']} | {m['native_gold']['tool_calls']} | {m['native_gold']['file_rec']} |
| **mcp_lean** (map+pack+expand) | {m['mcp_lean']['wall_ms']} | {m['mcp_lean']['out_tokens']} | {m['mcp_lean']['tool_calls']} | {m['mcp_lean']['file_rec']} |
| mcp_full (map+pack full) | {m['mcp_full']['wall_ms']} | {m['mcp_full']['out_tokens']} | {m['mcp_full']['tool_calls']} | {m['mcp_full']['file_rec']} |

**native / mcp_lean:** tokens ×{summary['token_ratio_native_over_mcp_lean']}, time ×{summary['time_ratio_native_over_mcp_lean']}

Per-problem details: `{OUT.as_posix()}`.
"""
    OUT_MD.write_text(md, encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print("wrote", OUT, OUT_MD)
    return report


if __name__ == "__main__":
    run()
