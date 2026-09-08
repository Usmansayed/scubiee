"""One-shot Trace Director: BM25+Graphify propose → LLM TRACE PLAN → heatmap.

Arms:
  A — fast cards (no body)
  B — body director (~60 lines)
  C — rich judge (body + dense; KEEP/DROP only)
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.ollama_client import OllamaResult, ollama_generate
from trace_lab.retrieve import LexicalIndex, normalize
from trace_lab.types import GoldCase, HeatCell, Heatmap, TraceNode

Arm = Literal["A", "B", "C"]

_MAX_ISLAND = 28
_MAX_HOPS = 4
_BODY_LINES_A = 15  # even "fast" arm gets real code context
_BODY_LINES_B = 45
_HOT = 0.85
_WARM = 0.38
_COLD = 0.08
_EXPAND_HOT = 0.70

_SYSTEM_DIRECTOR = """You are helping an AI coding agent build a CONTEXT HEATMAP.
You are given:
1) The agent's TASK (natural language) and the exact SEED symbol where tracing starts
2) The SEED's source code
3) A GRAPHIFY/AST call-graph among numbered candidates
4) Numbered candidate functions with code snippets

Your job: decide which numbered candidates the agent MUST read to complete the TASK starting from the SEED.
- Follow the call/import graph from the seed for THIS task only.
- DROP shared utilities that other features also use if they are not on this task's path.
- DROP siblings that are nearby in the graph but serve a different feature.

Reply with ONLY these lines (bare integers, no # prefixes):
INTENT: <max 10 words restating the task>
KEEP: <ids on the true task path, max 14>
DROP: <ids that are off-task / traps>
HUBS: <shared utilities to avoid unless required>
EXPAND: <id:calls or id:used_by if one more hop needed, else NONE>
STOP: <ids that are dead-ends for this task, else NONE>
NOTE: <max 12 words>"""

_SYSTEM_JUDGE = """You are helping an AI coding agent build a CONTEXT HEATMAP.
You get TASK + SEED source + Graphify call-graph + numbered candidates with code.
KEEP only candidates on the true path for THIS task from the seed.
DROP off-task neighbors and shared hubs used by other features.
Reply ONLY:
INTENT: <max 10 words>
KEEP: <ids, max 14>
DROP: <ids>
NOTE: <max 12 words>
Bare integers only (no #)."""


@dataclass
class TracePlan:
    intent: str = ""
    keep: set[int] = field(default_factory=set)
    drop: set[int] = field(default_factory=set)
    hubs: set[int] = field(default_factory=set)
    expand: list[tuple[int, str]] = field(default_factory=list)
    stop: set[int] = field(default_factory=set)
    note: str = ""
    raw: str = ""


@dataclass
class DirectorPack:
    arm: Arm
    numbered: list[str]  # node ids in #1.. order (1-based)
    prompt: str
    struct_scores: dict[str, float]
    why: dict[str, str]
    edges: list[tuple[str, str, str]]


def _neighbors(
    uid: str,
    ast: AstTraceGraph,
    gfy: AstTraceGraph | None,
) -> list[tuple[str, str, float]]:
    out: list[tuple[str, str, float]] = []
    seen: set[tuple[str, str]] = set()

    def add(vid: str, rel: str, w: float) -> None:
        key = (vid, rel)
        if key in seen or vid == uid:
            return
        seen.add(key)
        out.append((vid, rel, w))

    for g in (ast, gfy):
        if g is None:
            continue
        for vid, rel, w in g.neighbors(uid, directed=False):
            tag = rel if g is ast else f"g:{rel}"
            add(vid, tag, w)
    return out


def propose_island(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    ast: AstTraceGraph,
    lex: LexicalIndex,
    gfy: AstTraceGraph | None,
    *,
    max_nodes: int = _MAX_ISLAND,
) -> tuple[dict[str, float], dict[str, str], list[tuple[str, str, str]]]:
    """BM25 soft seeds + BFS on AST∪Graphify."""
    seed = case.seed.id
    if seed not in nodes:
        raise KeyError(seed)
    bm = normalize(lex.bm25_scores(case.query))
    scores: dict[str, float] = {seed: 1.0}
    why: dict[str, str] = {seed: "seed"}
    edges: list[tuple[str, str, str]] = []

    # Soft BM25 entry points
    for nid, sc in sorted(bm.items(), key=lambda kv: -kv[1])[:8]:
        if nid not in nodes or nodes[nid].kind == "class":
            continue
        if sc < 0.15:
            break
        scores[nid] = max(scores.get(nid, 0.0), 0.55 + 0.4 * sc)
        why.setdefault(nid, f"bm25:{sc:.2f}")

    q: deque[tuple[str, int]] = deque([(seed, 0)])
    seen = {seed}
    while q and len(scores) < max_nodes:
        uid, hop = q.popleft()
        if hop >= _MAX_HOPS:
            continue
        for vid, rel, w in _neighbors(uid, ast, gfy):
            if vid not in nodes or nodes[vid].kind == "class":
                continue
            edges.append((uid, vid, rel))
            incoming = scores.get(uid, 0.3) * max(w, 0.35) * (0.9**hop)
            if incoming < 0.08 and vid not in scores:
                continue
            if vid not in scores or incoming > scores[vid]:
                scores[vid] = max(scores.get(vid, 0.0), min(0.95, incoming))
                why[vid] = f"{rel}←{nodes[uid].symbol.split('.')[-1]}"
            if vid not in seen and len(scores) < max_nodes:
                seen.add(vid)
                q.append((vid, hop + 1))

    # Fill with top BM25 if island thin
    if len(scores) < min(24, max_nodes):
        for nid, sc in sorted(bm.items(), key=lambda kv: -kv[1]):
            if nid in scores or nid not in nodes or nodes[nid].kind == "class":
                continue
            scores[nid] = 0.35 + 0.3 * sc
            why[nid] = f"bm25_fill:{sc:.2f}"
            if len(scores) >= max_nodes:
                break
    return scores, why, edges


def _body_slice(node: TraceNode, max_lines: int) -> str:
    lines = (node.text or "").splitlines()
    if not lines:
        return "(empty)"
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[:max_lines]) + "\n..."


def _short(nid: str, nodes: dict[str, TraceNode]) -> str:
    n = nodes[nid]
    return f"{n.file}::{n.symbol}"


def _links_for(
    nid: str,
    idx: dict[str, int],
    edges: list[tuple[str, str, str]],
    *,
    limit: int = 8,
) -> str:
    bits: list[str] = []
    for u, v, rel in edges:
        if u == nid and v in idx:
            bits.append(f"-{rel}->#{idx[v]}")
        elif v == nid and u in idx:
            bits.append(f"<-{rel}-#{idx[u]}")
        if len(bits) >= limit:
            break
    return ", ".join(bits) if bits else "none"


def build_pack(
    arm: Arm,
    case: GoldCase,
    nodes: dict[str, TraceNode],
    scores: dict[str, float],
    why: dict[str, str],
    edges: list[tuple[str, str, str]],
    lex: LexicalIndex,
    dense: dict[str, float] | None = None,
) -> DirectorPack:
    bm = normalize(lex.bm25_scores(case.query))
    seed_id = case.seed.id
    seed_node = nodes[seed_id]

    def rank_key(nid: str) -> float:
        d = (dense or {}).get(nid, 0.0) if arm == "C" else 0.0
        # Prefer graph distance / struct score, then BM25 — not vague lexical soup
        return 0.65 * scores.get(nid, 0.0) + 0.20 * bm.get(nid, 0.0) + 0.15 * d

    rest = sorted((n for n in scores if n != seed_id), key=rank_key, reverse=True)
    ordered = [seed_id] + rest
    ordered = ordered[:_MAX_ISLAND]
    idx = {nid: i for i, nid in enumerate(ordered, start=1)}

    body_lines = _BODY_LINES_B if arm in ("B", "C") else _BODY_LINES_A

    # --- Graphify-first edge view (human readable) ---
    gfy_lines: list[str] = []
    ast_lines: list[str] = []
    for u, v, rel in edges:
        if u not in idx or v not in idx:
            continue
        line = f"  #{idx[u]} {_short(u, nodes).split('::')[-1]}  --{rel}-->  #{idx[v]} {_short(v, nodes).split('::')[-1]}"
        if rel.startswith("g:"):
            gfy_lines.append(line)
        else:
            ast_lines.append(line)
        if len(gfy_lines) + len(ast_lines) >= 100:
            break

    # --- Candidate cards with code + graph links ---
    cards: list[str] = []
    for i, nid in enumerate(ordered, start=1):
        node = nodes[nid]
        tag = "SEED" if nid == seed_id else "CAND"
        head = (
            f"### [{tag}] #{i}  {_short(nid, nodes)}  [{node.kind}]\n"
            f"struct={scores.get(nid, 0):.2f}  bm25={bm.get(nid, 0):.2f}  via={why.get(nid, '')}\n"
            f"graph_links: {_links_for(nid, idx, edges)}"
        )
        if arm == "C" and dense is not None:
            head += f"  dense={dense.get(nid, 0):.2f}"
        # Always include code for seed; candidates get body_lines
        lines = body_lines if nid != seed_id else max(body_lines, 30)
        cards.append(f"{head}\n```\n{_body_slice(node, lines)}\n```")

    task_block = f"""## TASK (agent request — follow this exactly)
{case.query}

## SEED (trace starts here — always KEEP #1)
id: {seed_id}
file: {seed_node.file}
symbol: {seed_node.symbol}
kind: {seed_node.kind}
lines: {seed_node.start_line}-{seed_node.end_line}

### SEED SOURCE
```
{_body_slice(seed_node, 40)}
```
"""

    graph_block = f"""## GRAPHIFY CALL GRAPH (among candidates)
{chr(10).join(gfy_lines) if gfy_lines else '  (no graphify edges in pack — using AST edges)'}

## AST / STRUCTURAL EDGES
{chr(10).join(ast_lines[:40]) if ast_lines else '  (none)'}
"""

    how_block = """## HOW TO DECIDE
1. Start at SEED (#1). Walk Graphify/AST edges that serve the TASK.
2. KEEP nodes on that path (credentials/user-load/etc. as the TASK says).
3. DROP nodes that are only BM25-similar or belong to other features.
4. Shared hubs (http, log, track) → HUBS/DROP unless the TASK needs them.
"""

    if arm == "C":
        how_block += "5. Output KEEP/DROP only.\n"
    else:
        how_block += "5. Output full TRACE PLAN.\n"

    parts = [
        task_block.strip(),
        graph_block.strip(),
        how_block.strip(),
        "## CANDIDATES (numbered — use these ids in KEEP/DROP)",
        "\n\n".join(cards),
    ]

    return DirectorPack(
        arm=arm,
        numbered=ordered,
        prompt="\n\n".join(parts),
        struct_scores=scores,
        why=why,
        edges=edges,
    )


_ID_LIST = re.compile(r"#?\s*(\d+)(?:\s*,\s*#?\s*(\d+))*")
_ID_ANY = re.compile(r"#?\s*(\d+)")
_EXPAND_ONE = re.compile(r"#?\s*(\d+)\s*:\s*([A-Za-z_]+)")


def _parse_ids(line: str) -> set[int]:
    return {int(m.group(1)) for m in _ID_ANY.finditer(line.split(":", 1)[-1])}


def parse_plan(text: str) -> TracePlan:
    plan = TracePlan(raw=text)
    cleaned = text.replace("```", "").strip()
    for line in cleaned.splitlines():
        line = line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("INTENT:"):
            plan.intent = line.split(":", 1)[1].strip()[:120]
        elif upper.startswith("KEEP:"):
            plan.keep = _parse_ids(line)
        elif upper.startswith("DROP:"):
            plan.drop = _parse_ids(line)
        elif upper.startswith("HUBS:"):
            plan.hubs = _parse_ids(line)
        elif upper.startswith("EXPAND:"):
            if "NONE" in upper:
                continue
            for m in _EXPAND_ONE.finditer(line):
                plan.expand.append((int(m.group(1)), m.group(2).lower()))
        elif upper.startswith("STOP:"):
            if "NONE" in upper:
                continue
            plan.stop = _parse_ids(line)
        elif upper.startswith("NOTE:"):
            plan.note = line.split(":", 1)[1].strip()[:80]
    return plan


def execute_plan(
    pack: DirectorPack,
    plan: TracePlan,
    nodes: dict[str, TraceNode],
    ast: AstTraceGraph,
    gfy: AstTraceGraph | None,
    *,
    strategy: str,
) -> Heatmap:
    id_of = {i: nid for i, nid in enumerate(pack.numbered, start=1)}
    # Precision-first: everything cold unless LLM KEEP / explicit EXPAND / seed
    scores: dict[str, float] = {nid: _WARM for nid in pack.numbered}
    why = {nid: pack.why.get(nid, "pack") for nid in pack.numbered}

    keep_ids = {id_of[i] for i in plan.keep if i in id_of}
    drop_ids = {id_of[i] for i in plan.drop if i in id_of}
    hub_ids = {id_of[i] for i in plan.hubs if i in id_of}
    stop_ids = {id_of[i] for i in plan.stop if i in id_of}

    for nid in pack.numbered:
        if nid in drop_ids:
            scores[nid] = _COLD
            why[nid] = "llm:DROP"
        elif nid in keep_ids:
            scores[nid] = _HOT
            why[nid] = "llm:KEEP"
        elif nid in hub_ids:
            scores[nid] = _COLD
            why[nid] = "llm:HUB"

    # EXPAND only when the plan explicitly asks (not auto from every KEEP)
    expand_from: list[tuple[str, str]] = []
    for num, rel in plan.expand:
        if num in id_of:
            expand_from.append((id_of[num], rel))

    for src, rel_filter in expand_from:
        if src in stop_ids:
            continue
        for vid, rel, w in _neighbors(src, ast, gfy):
            if vid not in nodes or nodes[vid].kind == "class":
                continue
            if rel_filter != "any" and rel_filter not in rel.lower():
                continue
            if vid in drop_ids or vid in stop_ids:
                continue
            if vid in keep_ids:
                continue
            scores[vid] = max(scores.get(vid, 0.0), _EXPAND_HOT)
            why[vid] = f"llm:EXPAND:{rel}"

    # Seed always hot
    for nid, wwhy in why.items():
        if wwhy == "seed":
            scores[nid] = 1.0

    cells = [
        HeatCell(
            node_id=nid,
            score=round(sc, 4),
            why=why.get(nid, "director"),
            path=(nid,),
        )
        for nid, sc in scores.items()
        if sc > 0.05 and nid in nodes
    ]
    cells.sort(key=lambda c: -c.score)
    return Heatmap(
        strategy=strategy,
        cells=cells,
        extra={
            "arm": pack.arm,
            "plan_intent": plan.intent,
            "plan_note": plan.note,
            "n_pack": len(pack.numbered),
            "keep": sorted(keep_ids),
            "drop": sorted(drop_ids),
        },
    )


def run_director(
    arm: Arm,
    case: GoldCase,
    nodes: dict[str, TraceNode],
    ast: AstTraceGraph,
    lex: LexicalIndex,
    gfy: AstTraceGraph | None,
    *,
    dense: dict[str, float] | None = None,
    model: str = "qwen3.5-0.8b-q4",
) -> tuple[Heatmap, TracePlan, OllamaResult, DirectorPack]:
    scores, why, edges = propose_island(case, nodes, ast, lex, gfy)
    # Ensure seed why
    why[case.seed.id] = "seed"
    scores[case.seed.id] = 1.0
    pack = build_pack(arm, case, nodes, scores, why, edges, lex, dense=dense)
    system = _SYSTEM_JUDGE if arm == "C" else _SYSTEM_DIRECTOR
    # Larger ctx for body arms
    num_ctx = 16384 if arm in ("B", "C") else 12288
    num_predict = 90 if arm == "C" else 110
    result = ollama_generate(
        pack.prompt,
        model=model,
        system=system,
        num_predict=num_predict,
        num_ctx=num_ctx,
    )
    plan = parse_plan(result.text)
    n = len(pack.numbered)
    # If model keeps almost everything, collapse to top joint ranks (precision rescue)
    if plan.keep and n and len(plan.keep) > max(14, int(0.55 * n)):
        plan.note = ((plan.note + " | ").lstrip(" |") + "clipped_keep").strip()
        plan.keep = set(sorted(plan.keep)[:14])
        plan.drop |= {i for i in range(1, n + 1) if i not in plan.keep}
    if not plan.keep and not plan.drop:
        plan.keep = set(range(1, min(10, n + 1)))
        plan.note = (plan.note + " | fallback_top").strip(" |")
    hm = execute_plan(pack, plan, nodes, ast, gfy, strategy=f"director_{arm}")
    return hm, plan, result, pack


def parse_plan_selftest() -> None:
    sample = """INTENT: pricing only
KEEP: #1, #3, #7
DROP: 2, 5, 9
HUBS: 4
EXPAND: 3:calls, 7:used_by
STOP: 4
NOTE: drop notify path
"""
    p = parse_plan(sample)
    assert p.keep == {1, 3, 7}, p.keep
    assert p.drop == {2, 5, 9}
    assert p.hubs == {4}
    assert (3, "calls") in p.expand
    assert p.stop == {4}
