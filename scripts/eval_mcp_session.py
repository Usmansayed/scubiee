"""Exercise the running Context Engine MCP end to end and grade it.

Drives the real server over stdio (spawned from .cursor/mcp.json, exactly as
Cursor does) through the workflow the agent rule prescribes:

    map -> expand            (cold start)
    recall -> focus -> expand (follow-up)
    workspace                 (heatmap / pin / clear)

Grades three things the toolkit claims: it finds the right code, its handles
materialise real file content, and it is cheaper than reading files outright.

    python scripts/eval_mcp_session.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from mcp_stdio_client import McpStdioClient  # noqa: E402

# Queries a developer would actually ask, with the file that answers each.
CASES: list[tuple[str, tuple[str, ...]]] = [
    ("how do we decide token budgets when savings mode is on", ("pipeline/session_store.py",)),
    ("track which files are hot in the current working session", ("pipeline/work_session.py",)),
    ("start the background service and recover when it is hung", ("pipeline/daemon.py",)),
    ("talk to the running service over http and check if it is healthy", ("pipeline/client.py",)),
    (
        "detect which files changed since the last index using hashes",
        ("pipeline/merkle.py", "pipeline/root_probe.py", "pipeline/incremental.py"),
    ),
    (
        "compress vectors so the index fits in memory",
        ("pipeline/turbo_quant.py", "pipeline/faiss_store.py", "pipeline/vectordb.py"),
    ),
]

# len/4 is the usual rough token ratio for source-like text. Only used to
# compare MCP output against reading the same files, so bias cancels out.
CHARS_PER_TOKEN = 4


def _tokens(text: str) -> int:
    return round(len(text) / CHARS_PER_TOKEN)


def _targets(card: dict) -> list[dict]:
    return [t for t in (card.get("targets") or []) if isinstance(t, dict)]


def _norm(p: str) -> str:
    return str(p).replace("\\", "/").lstrip("./")


class Report:
    def __init__(self) -> None:
        self.checks: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append((name, bool(ok), detail))
        return bool(ok)

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [c for c in self.checks if not c[1]]

    def render(self) -> str:
        lines = []
        for name, ok, detail in self.checks:
            mark = "PASS" if ok else "FAIL"
            lines.append(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(ROOT / ".cursor" / "mcp.json"))
    ap.add_argument("--server", default="context-engine")
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    rep = Report()
    out: dict = {}

    with McpStdioClient.from_config(args.config, args.server) as mcp:
        tools = mcp.list_tools()
        rep.check(
            "server exposes the documented toolkit",
            tools == ["expand", "focus", "map", "recall", "status", "workspace"],
            ", ".join(tools),
        )

        status = mcp.call("status")
        rep.check("engine reports healthy", bool(status.get("ok")), str(status.get("repo")))
        rep.check(
            "server is bound to this repo",
            Path(str(status.get("repo") or "x")).resolve() == ROOT.resolve(),
            str(status.get("repo")),
        )

        mcp.call("workspace", action="clear")

        # --- cold start: map should locate the answer -----------------------
        hits, ranks, map_tokens = 0, [], 0
        per_case = []
        first_handle, first_file = "", ""
        for query, expected in CASES:
            text = mcp.call_text("map", query=query)
            map_tokens += _tokens(text)
            card = json.loads(text)
            targets = _targets(card)
            files = [_norm(t.get("file") or "") for t in targets]
            rank = next(
                (i for i, f in enumerate(files, 1) if any(f.endswith(e) for e in expected)),
                None,
            )
            if rank:
                hits += 1
                ranks.append(rank)
            if not first_handle and targets:
                first_handle = targets[0].get("handle") or ""
                first_file = files[0]
            per_case.append(
                {"query": query, "rank": rank, "returned": files, "tokens": _tokens(text)}
            )

        hit_rate = hits / len(CASES)
        mrr = sum(1 / r for r in ranks) / len(CASES)
        rep.check(f"map finds the answer ({hits}/{len(CASES)})", hit_rate >= 0.75, f"mrr={mrr:.3f}")

        # --- handles must materialise real file content ---------------------
        body = mcp.call("expand", handle=first_handle) if first_handle else {}
        expand_text = str(body.get("text") or "")
        rep.check("expand returns a body for a map handle", bool(expand_text), first_handle)
        on_disk = ""
        if first_file and (ROOT / first_file).is_file():
            on_disk = (ROOT / first_file).read_text(encoding="utf-8", errors="ignore")
        probe = next((ln.strip() for ln in expand_text.splitlines() if len(ln.strip()) > 30), "")
        rep.check(
            "expanded text really comes from that file",
            bool(probe) and probe in on_disk,
            first_file,
        )

        # --- follow-up: recall then focus -----------------------------------
        recall = mcp.call("recall")
        spans = recall.get("spans") or []
        rep.check("recall lists spans already paid for", len(spans) > 0, f"n={len(spans)}")

        focus1 = mcp.call("focus", path="packages/pipeline/daemon.py")
        rep.check("focus by path returns a handle", bool(focus1.get("handle")), focus1.get("status", ""))
        focus2 = mcp.call("focus", path="packages/pipeline/daemon.py")
        rep.check(
            "repeat focus is deduped as already_in_session",
            focus2.get("status") == "already_in_session",
            str(focus2.get("status")),
        )

        ws = mcp.call("workspace", action="show")
        heat = [_norm(h.get("file") or "") for h in (ws.get("heatmap") or [])]
        rep.check(
            "workspace heatmap tracks touched files",
            any("daemon.py" in f for f in heat),
            f"top={heat[:3]}",
        )

        # --- cost: MCP output vs reading the same files ---------------------
        read_tokens = 0
        for case in per_case:
            for f in case["returned"][:1]:
                p = ROOT / f
                if p.is_file():
                    read_tokens += _tokens(p.read_text(encoding="utf-8", errors="ignore"))
        saved = 1 - (map_tokens / read_tokens) if read_tokens else 0.0
        rep.check(
            "map is cheaper than reading the top hit of each query",
            map_tokens < read_tokens,
            f"{map_tokens} vs {read_tokens} tokens ({saved:.0%} less)",
        )

        out = {
            "tools": tools,
            "repo": status.get("repo"),
            "hit_rate": round(hit_rate, 3),
            "mrr": round(mrr, 3),
            "map_tokens": map_tokens,
            "read_tokens_top_hits": read_tokens,
            "savings_vs_reading": round(saved, 3),
            "cases": per_case,
            "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in rep.checks],
        }

    print(rep.render())
    print(
        f"\nhit_rate={hit_rate:.0%}  mrr={mrr:.3f}  "
        f"map={map_tokens} tok vs read={read_tokens} tok ({saved:.0%} less)"
    )
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2), encoding="utf-8")

    failed = rep.failed
    print(
        f"\n{len(rep.checks) - len(failed)}/{len(rep.checks)} checks passed "
        f"=> {'PASS' if not failed else 'FAIL'}",
        file=sys.stderr,
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
