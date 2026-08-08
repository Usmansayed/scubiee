"""Metered tool wrappers for Cursor A/B (context tokens in, not LLM bill).

Each call appends to out/experiments/cursor_ab/meter/<arm>.jsonl and prints
a compact JSON result including tokens_in (tiktoken/estimate).

Usage examples:
  python scripts/experiments/cursor_ab/metered_tools.py graphify query_graph "browser session vanished"
  python scripts/experiments/cursor_ab/metered_tools.py d_channel_best search "browser session vanished"
  python scripts/experiments/cursor_ab/metered_tools.py d_channel_best query_graph "..."
  python scripts/experiments/cursor_ab/metered_tools.py d_channel_best grep_ident acquire
  python scripts/experiments/cursor_ab/metered_tools.py d_channel_best read_span path start end
  python scripts/experiments/cursor_ab/metered_tools.py summarize graphify
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ROOT / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))

OUT = ROOT / "out" / "experiments" / "cursor_ab" / "meter"
REPO = Path(
    __import__("os").environ.get("CTX_REPO")
    or __import__("os").environ.get("WORK_ROOT")
    or str(ROOT / "testdata" / "frontend-mcp")
).resolve()
# Dev A/B writes meters under cursor_dev_ab when WORK_ROOT is set.
_DEV = ROOT / "out" / "experiments" / "cursor_dev_ab"
if __import__("os").environ.get("WORK_ROOT") or (
    "cursor_dev_ab" in str(REPO).replace("\\", "/")
):
    OUT = _DEV / "meter"
GRAPH = (
    Path.home()
    / ".context-engine"
    / "projects"
    / "ce_312fe25bcf4127b33feb5275c4b918ec"
    / "graph.json"
)
CLI = ROOT / "scripts" / "experiments" / "cursor_ab" / "graphify_cli.py"


def _tokens(text: str) -> int:
    from pipeline.token_meter import estimate_tokens

    return int(estimate_tokens(text or ""))


def _log(arm: str, tool: str, args: dict, text: str, ms: float) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    tok = _tokens(text)
    row = {
        "ts": time.time(),
        "arm": arm,
        "tool": tool,
        "args": args,
        "ms": round(ms, 1),
        "chars": len(text or ""),
        "tokens_in": tok,
    }
    with (OUT / f"{arm}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    # Keep agent-facing payload, but stamp meter on top.
    return {"meter": row, "result": text}


def graphify_query(question: str, budget: int = 1600) -> dict:
    import subprocess

    t0 = time.perf_counter()
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "query_graph",
            question,
            "--graph",
            str(GRAPH),
            "--budget",
            str(budget),
        ],
        cwd=str(ROOT),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(PACKAGES)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    text = proc.stdout or proc.stderr or ""
    return _log("graphify", "query_graph", {"question": question, "budget": budget}, text, (time.perf_counter() - t0) * 1000)


def graphify_neighbors(label: str) -> dict:
    import subprocess

    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, str(CLI), "get_neighbors", label, "--graph", str(GRAPH)],
        cwd=str(ROOT),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(PACKAGES)},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    text = proc.stdout or proc.stderr or ""
    return _log("graphify", "get_neighbors", {"label": label}, text, (time.perf_counter() - t0) * 1000)


def ce_search(query: str, top_k: int = 6) -> dict:
    from pipeline.client import EngineClient

    t0 = time.perf_counter()
    c = EngineClient()
    raw = c.search(query, top_k=top_k, path=str(REPO))
    hits = []
    for h in raw.get("hits") or []:
        hits.append(
            {
                "rank": h.get("rank"),
                "file": h.get("file") or h.get("path"),
                "score": h.get("score"),
                "start_line": h.get("start_line"),
                "end_line": h.get("end_line"),
                "why": (h.get("why") or "")[:180],
                "source": h.get("source"),
                "channels": h.get("channels"),
            }
        )
    text = json.dumps(
        {
            "ok": raw.get("ok", True),
            "retrieve_mode": (raw.get("timings") or {}).get("retrieve_mode"),
            "hits": hits,
        },
        indent=2,
    )
    return _log("d_channel_best", "search", {"query": query, "top_k": top_k}, text, (time.perf_counter() - t0) * 1000)


def ce_query_graph(question: str) -> dict:
    from pipeline.client import EngineClient

    t0 = time.perf_counter()
    c = EngineClient()
    raw = c.query_graph(question, keep=5, neighbor_keep=3, max_chars=350, repo=str(REPO))
    text = json.dumps(raw, indent=2, default=str)
    return _log("d_channel_best", "query_graph", {"question": question}, text, (time.perf_counter() - t0) * 1000)


def ce_grep_ident(ident: str) -> dict:
    from pipeline.client import EngineClient

    t0 = time.perf_counter()
    c = EngineClient()
    raw = c.grep_ident(ident, keep=4, max_chars=450, path=str(REPO))
    text = json.dumps(raw, indent=2, default=str)
    return _log("d_channel_best", "grep_ident", {"ident": ident}, text, (time.perf_counter() - t0) * 1000)


def ce_read_span(path: str, start: int = 0, end: int = 0) -> dict:
    from pipeline.client import EngineClient

    t0 = time.perf_counter()
    c = EngineClient()
    raw = c.read_span(
        path,
        start_line=start or None,
        end_line=end or None,
        max_chars=600,
        repo=str(REPO),
    )
    text = json.dumps(raw, indent=2, default=str)
    return _log(
        "d_channel_best",
        "read_span",
        {"path": path, "start": start, "end": end},
        text,
        (time.perf_counter() - t0) * 1000,
    )


def summarize(arm: str) -> dict:
    path = OUT / f"{arm}.jsonl"
    if not path.is_file():
        return {"arm": arm, "calls": 0, "tokens_in": 0}
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {
        "arm": arm,
        "calls": len(rows),
        "tokens_in": sum(int(r.get("tokens_in") or 0) for r in rows),
        "ms": round(sum(float(r.get("ms") or 0) for r in rows), 1),
        "tools": [r.get("tool") for r in rows],
    }


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    arm, cmd, *rest = sys.argv[1:]
    if cmd == "summarize":
        print(json.dumps(summarize(arm), indent=2))
        return 0
    if arm == "graphify":
        if cmd == "query_graph":
            print(json.dumps(graphify_query(" ".join(rest) or ""), indent=2)[:12000])
            return 0
        if cmd == "get_neighbors":
            print(json.dumps(graphify_neighbors(rest[0] if rest else ""), indent=2)[:12000])
            return 0
    if arm == "d_channel_best":
        if cmd == "search":
            print(json.dumps(ce_search(" ".join(rest) or ""), indent=2)[:12000])
            return 0
        if cmd == "query_graph":
            print(json.dumps(ce_query_graph(" ".join(rest) or ""), indent=2)[:12000])
            return 0
        if cmd == "grep_ident":
            print(json.dumps(ce_grep_ident(rest[0] if rest else ""), indent=2)[:12000])
            return 0
        if cmd == "read_span":
            path = rest[0] if rest else ""
            start = int(rest[1]) if len(rest) > 1 else 0
            end = int(rest[2]) if len(rest) > 2 else 0
            print(json.dumps(ce_read_span(path, start, end), indent=2)[:12000])
            return 0
    print(json.dumps({"ok": False, "error": f"unknown {arm} {cmd}"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
