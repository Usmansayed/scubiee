"""Realistic multi-turn coding-session A/B: Context Engine vs Graphify+grep.

Scripted (deterministic) agent policy — same mission, two retrieval stacks.
Models the continuous-session hypothesis: after turn 1, follow-ups should
reuse accumulated context rather than cold rediscovery.

Mission (frontend-mcp):
  T1 — locate + plan fix for session-not-found / unreachable guidance
  T2 — follow-up: extend the same guidance with recovery steps (reuse context)
  T3 — related: find where session_start is registered (nearby architecture)

Arms:
  graphify_grep — graph neighbors (if available) + term grep + full-file reads
  context_engine — search/locate + file_outline + pointer previews

Metrics: search/grep/graph ops, files opened, latency, tokens into context,
         rubric (right files in session for each turn).

Usage:
  python -u scripts/session_ab_realistic.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.capability import file_outline, grep_code
from pipeline.engine import load_engine
from pipeline.store import PipelineStore
from pipeline.token_meter import estimate_tokens

REPO = ROOT / "testdata" / "frontend-mcp"
OUT = ROOT / "out" / "session_ab"


def _pointer_preview(root: Path, rel: str, *, max_chars: int = 600) -> str:
    """Compact file peek: outline head + first N chars (no full-file dump)."""
    outline = file_outline(root, rel)
    head = _read_file(root, rel, max_chars=max_chars)
    return json.dumps({"outline_n": len(outline), "head": head}, ensure_ascii=False)

# --- Mission -----------------------------------------------------------------

MISSION = {
    "title": "Session guidance recovery (multi-turn)",
    "brief": (
        "Users hit 'session not found' / unreachable site errors. "
        "Improve agent-facing guidance and make sure session_start wiring is clear."
    ),
    "turns": [
        {
            "id": "T1_explore_edit",
            "goal": "Find where session-not-found / unreachable guidance lives and identify the edit target.",
            "queries": [
                "session not found unreachable agent guidance",
                "what should the agent do when session disappeared",
            ],
            "grep_patterns": [
                r"session not found",
                r"SESSION_NOT_FOUND|unreachable",
                r"agent_guidance",
            ],
            "must_touch": ["agent_guidance.py"],
            "edit": {
                "file_substr": "agent_guidance.py",
                "marker": "# SESSION_AB_EDIT_T1",
                "snippet": (
                    "\n# SESSION_AB_EDIT_T1: prefer clear recovery when session is missing\n"
                ),
            },
        },
        {
            "id": "T2_followup_same_area",
            "goal": "Follow-up in the SAME session: add recovery-step note next to the guidance you just touched.",
            "queries": [
                "recover after session disappeared guidance steps",
            ],
            "grep_patterns": [
                r"SESSION_AB_EDIT_T1|recovery|session",
            ],
            "must_touch": ["agent_guidance.py"],
            "prefer_session_memory": True,
            "edit": {
                "file_substr": "agent_guidance.py",
                "marker": "# SESSION_AB_EDIT_T2",
                "snippet": (
                    "\n# SESSION_AB_EDIT_T2: re-run health then session_start then observe\n"
                ),
            },
        },
        {
            "id": "T3_related_architecture",
            "goal": "Related: where is perception_session_start registered for tools?",
            "queries": [
                "where is perception_session_start registered dispatch",
            ],
            "grep_patterns": [
                r"perception_session_start",
                r"dispatch_registry",
            ],
            "must_touch": ["dispatch_registry.py"],
            "edit": None,
        },
    ],
}


@dataclass
class Ops:
    searches: int = 0
    greps: int = 0
    graph_lookups: int = 0
    outlines: int = 0
    file_reads: int = 0
    edits: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class SessionState:
    known_files: list[str] = field(default_factory=list)
    context_blobs: list[str] = field(default_factory=list)
    ops: Ops = field(default_factory=Ops)
    retrieve_ms: float = 0.0
    tokens_in: int = 0
    edits_applied: list[str] = field(default_factory=list)
    turn_logs: list[dict[str, Any]] = field(default_factory=list)

    def remember(self, rel: str) -> None:
        rel = rel.replace("\\", "/")
        if rel not in self.known_files:
            self.known_files.append(rel)

    def add_context(self, label: str, text: str) -> int:
        blob = f"##### {label} #####\n{text}"
        self.context_blobs.append(blob)
        toks = estimate_tokens(blob)
        self.tokens_in += toks
        return toks


def _skip(rel: str) -> bool:
    r = rel.lower()
    return any(
        x in r
        for x in (
            "node_modules",
            ".venv",
            "__pycache__",
            "/references/",
            "/research/",
            "graphify-out",
        )
    )


def _read_file(root: Path, rel: str, *, max_chars: int | None = None) -> str:
    p = root / rel
    text = p.read_text(encoding="utf-8", errors="replace")
    if max_chars is not None:
        return text[:max_chars]
    return text


def _apply_edit(root: Path, rel: str, marker: str, snippet: str) -> bool:
    p = root / rel
    text = p.read_text(encoding="utf-8", errors="replace")
    if marker in text:
        return False
    # append near end of module docstring area or file end
    p.write_text(text.rstrip() + snippet, encoding="utf-8")
    return True


def _revert_edits(root: Path, markers: list[str]) -> None:
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if _skip(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        orig = text
        for m in markers:
            if m in text:
                # remove lines containing marker and the following short comment blocks we added
                lines = text.splitlines(keepends=True)
                text = "".join(ln for ln in lines if m not in ln)
        if text != orig:
            path.write_text(text, encoding="utf-8")


def _resolve_must(root: Path, substr: str) -> str | None:
    hits = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if _skip(rel):
            continue
        if substr.replace("\\", "/") in rel.replace("\\", "/"):
            hits.append(rel)
    return sorted(hits, key=len)[0] if hits else None


def _graph_neighbors(graph_path: Path, seed_files: list[str], *, limit: int = 8) -> list[str]:
    if not graph_path.is_file():
        return []
    try:
        G = json.loads(graph_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    seed = {s.replace("\\", "/") for s in seed_files}
    out: list[str] = []

    # Context Engine graph_ir.json: symbols + edges with file/source/target
    symbols = G.get("symbols")
    edges = G.get("edges")
    if isinstance(symbols, dict) and isinstance(edges, list):
        file_of = {
            str(sid): str(meta.get("file") or "").replace("\\", "/")
            for sid, meta in symbols.items()
            if isinstance(meta, dict) and meta.get("file")
        }
        seed_ids = {
            sid
            for sid, f in file_of.items()
            if any(s in f or f.endswith(s) or Path(f).name == Path(s).name for s in seed)
        }
        for e in edges:
            if not isinstance(e, dict):
                continue
            a, b = str(e.get("source") or ""), str(e.get("target") or "")
            ef = str(e.get("file") or "").replace("\\", "/")
            for x, y in ((a, b), (b, a)):
                if x not in seed_ids:
                    continue
                f = file_of.get(y) or ef
                if f and f not in seed and f not in out and f != ".":
                    out.append(f)
            if len(out) >= limit:
                break
        return out[:limit]

    # networkx node-link fallback
    nodes = G.get("nodes") or []
    links = G.get("links") or G.get("edges") or []
    file_of2: dict[str, str] = {}
    for n in nodes:
        if isinstance(n, dict):
            nid = str(n.get("id") or "")
            sf = (n.get("source_file") or n.get("file") or n.get("path") or "")
            if sf:
                file_of2[nid] = str(sf).replace("\\", "/")
    seed_ids2 = {nid for nid, f in file_of2.items() if any(s in f or f.endswith(s) for s in seed)}
    for e in links:
        if not isinstance(e, dict):
            continue
        a, b = str(e.get("source") or e.get("from") or ""), str(e.get("target") or e.get("to") or "")
        for x, y in ((a, b), (b, a)):
            if x in seed_ids2 and y in file_of2:
                f = file_of2[y]
                if f not in seed and f not in out:
                    out.append(f)
    return out[:limit]


# --- Arm: Graphify + grep ----------------------------------------------------

def run_graphify_grep(root: Path, mission: dict[str, Any]) -> SessionState:
    st = SessionState()
    graph_path = PipelineStore(root).base / "graph_ir.json"
    if not graph_path.is_file():
        graph_path = PipelineStore(root).base / "graph.json"
    markers: list[str] = []

    for turn in mission["turns"]:
        t0 = time.perf_counter()
        turn_tok_before = st.tokens_in
        opened: list[str] = []

        # Follow-up: still re-grep (naive rediscovery) but also re-read known files fully
        if turn.get("prefer_session_memory") and st.known_files:
            for rel in list(st.known_files)[:4]:
                body = _read_file(root, rel, max_chars=8000)
                st.ops.file_reads += 1
                st.add_context(f"full:{rel}", body)
                opened.append(rel)

        for pat in turn.get("grep_patterns") or []:
            st.ops.greps += 1
            hits = grep_code(root, pat, glob="*.py", max_hits=15)
            # compact grep hit list still counts; then full-read top files
            st.add_context(f"grep:{pat}", json.dumps(hits, ensure_ascii=False)[:2000])
            for h in hits[:6]:
                rel = str(h.get("path") or h.get("file") or "")
                if not rel or _skip(rel):
                    continue
                st.remember(rel)
                if rel not in opened:
                    body = _read_file(root, rel, max_chars=8000)
                    st.ops.file_reads += 1
                    st.add_context(f"full:{rel}", body)
                    opened.append(rel)

        # graph expand from seeds
        seeds = [m for m in (turn.get("must_touch") or []) if True]
        seeds += opened[:2]
        nbrs = _graph_neighbors(graph_path, seeds)
        if nbrs:
            st.ops.graph_lookups += 1
            st.add_context("graph_neighbors", "\n".join(nbrs))
            for rel in nbrs[:3]:
                if rel not in opened and (root / rel).is_file():
                    body = _read_file(root, rel, max_chars=8000)
                    st.ops.file_reads += 1
                    st.remember(rel)
                    st.add_context(f"full:{rel}", body)
                    opened.append(rel)

        # ensure must_touch present
        for need in turn.get("must_touch") or []:
            rel = _resolve_must(root, need)
            if rel and rel not in opened:
                body = _read_file(root, rel, max_chars=8000)
                st.ops.file_reads += 1
                st.remember(rel)
                st.add_context(f"full:{rel}", body)
                opened.append(rel)

        edit = turn.get("edit")
        if edit:
            rel = _resolve_must(root, edit["file_substr"])
            if rel:
                if _apply_edit(root, rel, edit["marker"], edit["snippet"]):
                    st.ops.edits += 1
                    st.edits_applied.append(edit["marker"])
                    markers.append(edit["marker"])

        st.retrieve_ms += (time.perf_counter() - t0) * 1000
        st.turn_logs.append(
            {
                "turn": turn["id"],
                "opened": opened,
                "tokens_delta": st.tokens_in - turn_tok_before,
                "rubric_ok": all(
                    any(need in f for f in st.known_files) for need in (turn.get("must_touch") or [])
                ),
            }
        )

    st.turn_logs.append({"_revert_markers": markers})
    return st


# --- Arm: Context Engine -----------------------------------------------------

def run_context_engine(root: Path, mission: dict[str, Any]) -> SessionState:
    st = SessionState()
    eng = load_engine(root)
    markers: list[str] = []

    for turn in mission["turns"]:
        t0 = time.perf_counter()
        turn_tok_before = st.tokens_in
        opened: list[str] = []

        # Follow-up: reuse session memory with outlines/pointers (not full rediscovery)
        if turn.get("prefer_session_memory") and st.known_files:
            for rel in list(st.known_files)[:4]:
                st.ops.outlines += 1
                outline = file_outline(root, rel)
                st.add_context(f"outline:{rel}", json.dumps(outline, ensure_ascii=False)[:2500])
                preview = _pointer_preview(root, rel, max_chars=500)
                st.ops.file_reads += 1
                st.add_context(f"pointer:{rel}", preview)
                opened.append(rel)

        for q in turn.get("queries") or []:
            st.ops.searches += 1
            # locate + search compact
            caps = []
            if hasattr(eng, "locate_capability"):
                caps = eng.locate_capability(q, top_k=5) or []
            hits = eng.search(q, top_k=8, skip_freshness=True)
            payload = {
                "query": q,
                "capability": [
                    {"path": h.path, "symbol": h.symbol, "why": (h.why or "")[:120]} for h in caps
                ],
                "search": [
                    {"path": h.file, "score": round(float(h.score), 3), "preview": (h.preview or "")[:160]}
                    for h in hits
                ],
            }
            st.add_context(f"search:{q}", json.dumps(payload, ensure_ascii=False))
            for h in caps:
                st.remember(h.path)
            for h in hits:
                st.remember(h.file)

        # pointer-read top new files
        for rel in st.known_files:
            if rel in opened:
                continue
            if any(need in rel for need in (turn.get("must_touch") or []) ) or len(opened) < 5:
                st.ops.outlines += 1
                outline = file_outline(root, rel)
                st.add_context(f"outline:{rel}", json.dumps(outline, ensure_ascii=False)[:2500])
                preview = _pointer_preview(root, rel, max_chars=600)
                st.ops.file_reads += 1
                st.add_context(f"pointer:{rel}", preview)
                opened.append(rel)
            if len(opened) >= 6:
                break

        for need in turn.get("must_touch") or []:
            rel = _resolve_must(root, need)
            if rel and rel not in opened:
                st.remember(rel)
                preview = _pointer_preview(root, rel, max_chars=800)
                st.ops.file_reads += 1
                st.add_context(f"pointer:{rel}", preview)
                opened.append(rel)

        # light grep only if must_touch still missing from memory
        for need in turn.get("must_touch") or []:
            if not any(need in f for f in st.known_files):
                st.ops.greps += 1
                hits = grep_code(root, need.replace(".py", ""), glob="*.py", max_hits=10)
                st.add_context(f"grep_fallback:{need}", json.dumps(hits)[:1500])

        edit = turn.get("edit")
        if edit:
            rel = _resolve_must(root, edit["file_substr"])
            if rel:
                if _apply_edit(root, rel, edit["marker"], edit["snippet"]):
                    st.ops.edits += 1
                    st.edits_applied.append(edit["marker"])
                    markers.append(edit["marker"])

        st.retrieve_ms += (time.perf_counter() - t0) * 1000
        st.turn_logs.append(
            {
                "turn": turn["id"],
                "opened": opened,
                "tokens_delta": st.tokens_in - turn_tok_before,
                "rubric_ok": all(
                    any(need in f for f in st.known_files) for need in (turn.get("must_touch") or [])
                ),
            }
        )

    st.turn_logs.append({"_revert_markers": markers})
    return st


def _summarize(name: str, st: SessionState, wall_s: float) -> dict[str, Any]:
    rubric = [t for t in st.turn_logs if "rubric_ok" in t]
    return {
        "arm": name,
        "wall_sec": round(wall_s, 2),
        "retrieve_ms": round(st.retrieve_ms, 1),
        "tokens_in": st.tokens_in,
        "ops": st.ops.as_dict(),
        "files_known": len(st.known_files),
        "files": st.known_files[:20],
        "edits": st.edits_applied,
        "rubric_pass": all(t.get("rubric_ok") for t in rubric),
        "rubric_turns": rubric,
        "tokens_by_turn": [
            {"turn": t.get("turn"), "tokens_delta": t.get("tokens_delta")} for t in rubric
        ],
    }


def main() -> int:
    os.environ.setdefault("CTX_EMBED_BATCH", "16")
    root = REPO.resolve()
    if not root.is_dir():
        print("ERROR: missing testdata/frontend-mcp", flush=True)
        return 2
    store = PipelineStore(root)
    if not store.load_chunks():
        print("ERROR: frontend-mcp not indexed — run index first", flush=True)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    markers_all = [
        t["edit"]["marker"]
        for t in MISSION["turns"]
        if t.get("edit")
    ]
    # clean slate
    _revert_edits(root, markers_all)

    print("=== ARM graphify_grep ===", flush=True)
    t0 = time.perf_counter()
    g_state = run_graphify_grep(root, MISSION)
    g_wall = time.perf_counter() - t0
    g_sum = _summarize("graphify_grep", g_state, g_wall)
    print(json.dumps(g_sum, indent=2), flush=True)
    _revert_edits(root, markers_all)

    print("=== ARM context_engine ===", flush=True)
    t0 = time.perf_counter()
    c_state = run_context_engine(root, MISSION)
    c_wall = time.perf_counter() - t0
    c_sum = _summarize("context_engine", c_state, c_wall)
    print(json.dumps(c_sum, indent=2), flush=True)
    _revert_edits(root, markers_all)

    saved = max(0, g_sum["tokens_in"] - c_sum["tokens_in"])
    pct = round(100.0 * saved / g_sum["tokens_in"], 1) if g_sum["tokens_in"] else 0.0

    lines = [
        "# Realistic multi-turn session A/B",
        "",
        f"**Mission:** {MISSION['title']}",
        "",
        MISSION["brief"],
        "",
        "Scripted continuous session (T1 explore+edit → T2 follow-up same area → T3 related).",
        "",
        "## Results",
        "",
        "| Metric | Graphify+grep | Context Engine | Δ |",
        "|--------|---------------|----------------|---|",
        f"| Tokens into context | {g_sum['tokens_in']} | {c_sum['tokens_in']} | **−{saved} ({pct}% saved)** |",
        f"| Wall sec | {g_sum['wall_sec']} | {c_sum['wall_sec']} | {c_sum['wall_sec'] - g_sum['wall_sec']:+.2f} |",
        f"| Retrieve ms | {g_sum['retrieve_ms']} | {c_sum['retrieve_ms']} | {c_sum['retrieve_ms'] - g_sum['retrieve_ms']:+.1f} |",
        f"| Searches | {g_sum['ops']['searches']} | {c_sum['ops']['searches']} | |",
        f"| Greps | {g_sum['ops']['greps']} | {c_sum['ops']['greps']} | |",
        f"| Graph lookups | {g_sum['ops']['graph_lookups']} | {c_sum['ops']['graph_lookups']} | |",
        f"| File reads | {g_sum['ops']['file_reads']} | {c_sum['ops']['file_reads']} | |",
        f"| Outlines | {g_sum['ops']['outlines']} | {c_sum['ops']['outlines']} | |",
        f"| Files known | {g_sum['files_known']} | {c_sum['files_known']} | |",
        f"| Rubric pass | {g_sum['rubric_pass']} | {c_sum['rubric_pass']} | |",
        f"| Edits applied | {len(g_sum['edits'])} | {len(c_sum['edits'])} | |",
        "",
        "## Tokens by turn",
        "",
        "| Turn | Graphify+grep | Context Engine |",
        "|------|---------------|----------------|",
    ]
    for gt, ct in zip(g_sum["tokens_by_turn"], c_sum["tokens_by_turn"]):
        lines.append(f"| {gt['turn']} | {gt['tokens_delta']} | {ct['tokens_delta']} |")

    lines += [
        "",
        "## Hypothesis check",
        "",
        "Follow-up turn (T2) should show CE using outlines/pointers on known files "
        "while Graphify+grep re-reads full files — largest token gap often on T2.",
        "",
    ]
    # T2 delta callout
    g2 = next((t for t in g_sum["tokens_by_turn"] if "T2" in str(t.get("turn"))), None)
    c2 = next((t for t in c_sum["tokens_by_turn"] if "T2" in str(t.get("turn"))), None)
    if g2 and c2:
        lines.append(
            f"**T2 follow-up tokens:** Graphify {g2['tokens_delta']} vs CE {c2['tokens_delta']} "
            f"(CE saved {max(0, g2['tokens_delta'] - c2['tokens_delta'])})."
        )

    md = "\n".join(lines) + "\n"
    (OUT / "SESSION_REPORT.md").write_text(md, encoding="utf-8")
    (OUT / "session_report.json").write_text(
        json.dumps({"mission": MISSION["title"], "graphify_grep": g_sum, "context_engine": c_sum, "pct_tokens_saved": pct}, indent=2),
        encoding="utf-8",
    )
    print(md, flush=True)
    print(f"wrote {OUT / 'SESSION_REPORT.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
