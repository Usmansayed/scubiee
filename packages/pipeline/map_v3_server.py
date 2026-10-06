"""MCP stdio bridge: map_v3 — the session-study tool shape.

TWO OUTPUT configs on one `map` tool, each returning a COMPLETE unit so the
agent reaches the edit/answer in the fewest calls (sessions showed cost = calls,
and the two biggest leaks were wiring-trace chains `locate_wire->locate_wire`
(79x) and locate-then-read round-trips `find->read` (57x)). This surface folds
wiring INTO the body call.

Surface history: v0.3.142 narrowed the advertised surface from four configs to
TWO (find|focus). Usage mining showed find+focus = ~92% of real calls; `related`
was ~2% (near-dead) and `graph` ~5%. Fewer tools = simpler to reason about and to
explain. The old `related`/`graph` handlers are kept as HIDDEN graceful fallbacks
(an agent that still passes them is served, not errored) but they are not
advertised in the tool description, the schema enum, or the server instructions.

Inputs (what you know):
  query          - semantic intent (unknown location)
  anchor         - a chunk you already have: "file::symbol" | "file:line" | "file:a-b"
  names          - exact identifiers you'll touch
  include_bodies - whether focus returns full source

Outputs (config):
  find    - ranked locations + clustered bodies (where is X; returns the code).
            Also the way to ORIENT in a wide/unknown area (use a broad query) and
            to pull code related to a chunk you hold (put its names in the query) —
            the old graph/related jobs folded into one config.
  focus   - ONE unit: clustered bodies + one-hop wiring (callers/callees) +
            sibling symbol names. "Give me the code AND how it's wired, ready to edit."
            Collapses find->read and wire->wire into one call.

Reuses the validated engine/fs/search/outline/body helpers from map_v3_helpers;
adds only the config logic here.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from pipeline import map_v3_helpers as mv2
from pipeline.map_v3_helpers import (  # noqa: F401  (reused helpers)
    Out, _search, _grep, _outline, _enclosing, _numbered, _code_text, _norm,
    _lines, _kind_of, _in_scope, _label, _locate_target, _resolve_symbol_name,
    DEFAULT_BUDGET, BODY_CAP, PY_KEYWORDS,
)

PROJECT_ID = mv2.PROJECT_ID

BUDGET = {"find": 14000, "focus": 14000, "related": 12000, "graph": 6000}

SERVER_INSTRUCTIONS = (
    "Scubiee map = semantic code retrieval. ONE tool `map`, config = find | focus "
    "(+ gate/status for health).\n"
    "- find(query): you do NOT know where code lives. ONE query, ONE target -> ranked locations with "
    "the code inline. Also use find to ORIENT in a wide/unknown area (a broad query) and to pull code "
    "near a chunk you already hold (put its names/intent in the query).\n"
    "- focus(names|anchor): you DO know the symbol name(s) -> that symbol's full code + its "
    "callers/callees + sibling symbol names, in ONE unit. Edit from this; no follow-up grep.\n"
    "DECOMPOSE: a task that needs TWO distinct things is TWO calls, not one bundled query (a broad "
    "query mixing targets returns only the strongest and drops the other). When you already know a "
    "name, `focus` it FIRST; do not fold a known-name or structural lookup into a semantic find.\n"
    "map is a PARTNER to native Grep/Read: a known literal/import/path -> native tool. Act on the "
    "first good answer and STOP; never re-search what map already returned."
)


# ---------------------------------------------------------------------------
# helpers specific to v3
# ---------------------------------------------------------------------------

def _as_list(x):
    if x is None:
        return []
    return [x] if isinstance(x, str) else list(x)


def _top_level_symbols(rel: str) -> list[dict]:
    """Module-level functions/classes only (not methods), with line ranges."""
    return [s for s in _outline(rel) if "." not in str(s.get("symbol") or "")]


def _callers_of(name: str, defrel: str, a: int, b: int, cap: int = 6) -> list[str]:
    """file:line in <fn> for sites that call `name` (not its own body/def)."""
    out = []
    try:
        hits, _ = _grep(rf"\b{re.escape(name)}\s*\(", max_hits=120, scope="code")
    except Exception:  # noqa: BLE001
        hits = []
    for h in hits:
        hrel, ln = _norm(h.get("path")), int(h.get("line") or 0)
        if hrel == defrel and a <= ln <= b:
            continue
        if re.search(rf"\b(?:def|class)\s+{re.escape(name)}\b", str(h.get("text") or "")):
            continue
        enc = _enclosing(hrel, ln)
        out.append(f"{hrel}:{ln}" + (f" in {enc['symbol']}" if enc else ""))
        if len(out) >= cap:
            break
    return out


def _callees_in(rel: str, a: int, b: int, cap: int = 8) -> list[str]:
    """Repo-defined functions called inside the a..b body (same-file resolved)."""
    body = _code_text(rel, a + 1, b)
    local = {str(s.get("symbol") or "").split(".")[-1]: s for s in _outline(rel)}
    out, seen = [], set()
    for m in re.finditer(r"(?<![\w.])(?:(?:self|cls)\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\(", body):
        nm = m.group(1)
        if nm in PY_KEYWORDS or nm in seen:
            continue
        seen.add(nm)
        if nm in local:
            out.append(f"{rel}:{local[nm]['line']} {nm}")
        if len(out) >= cap:
            break
    return out


def _pack_bodies(out: "Out", cards: list[dict]) -> None:
    """Pack numbered bodies for the given cards, sharing the budget."""
    n = len(cards)
    for i, c in enumerate(cards):
        if out.room() < 400:
            break
        cap = out.room() - 200 if n == 1 else max(900, (out.room() - 200) // max(1, n - i))
        out.add(f"-- {_label(c)}  lines {c['start']}-{c['end']} --", force=True)
        rows, last = _numbered(c["file"], c["start"], c["end"], cap)
        for row in rows:
            out.add(row, force=True)
        if last < c["end"]:
            out.add(f"... +{c['end'] - last} more lines", force=True)


# ---------------------------------------------------------------------------
# configs
# ---------------------------------------------------------------------------

def cfg_find(a: dict) -> str:
    """map_v2 find, but A2: pack bodies for the top TWO clustered files (not just
    the single top file) so a cross-file edit needs no focus follow-up. The 2nd
    file is only added when its best hit scores within 75% of the top (see
    cluster_files handling in map_v2.cfg_find)."""
    a = dict(a)
    a.setdefault("cluster_files", 2)
    return mv2.cfg_find(a)


def _resolve_one(target: str) -> dict | None:
    """Resolve a single name / file::symbol / file:line to a located symbol."""
    loc = _locate_target(str(target))
    if "error" in loc:
        if "::" not in str(target) and ":" not in str(target):
            loc = _resolve_symbol_name(str(target))
        else:
            loc = None
    if not loc or not loc.get("symbol"):
        return None
    return loc


def cfg_focus(a: dict) -> str:
    """ONE unit for ONE OR MANY symbols: each symbol's code + callers + callees +
    sibling names, grouped by file. A1: a multi-symbol edit (even across files) is
    ONE focus call with all names, not one call per symbol - the dataset's #1
    waste pattern (locate_wire->locate_wire 79x / read_body->read_body 19x)."""
    # accept names=[...], anchor="x", or anchors=[...]
    targets = _as_list(a.get("names")) + _as_list(a.get("anchors"))
    if a.get("anchor"):
        targets.append(str(a["anchor"]))
    # de-dup preserving order
    seen_t: set = set()
    targets = [t for t in targets if not (t in seen_t or seen_t.add(t))]
    if not targets:
        return "error: focus needs names=[...] (one or more) or anchor=\"file::symbol\""

    resolved, missing, fuzzy = [], [], []
    seen_sym = set()
    for t in targets:
        loc = _resolve_one(t)
        if not loc:
            missing.append(t); continue
        # Flag a FUZZY resolve: the requested name doesn't match the symbol we
        # landed on (e.g. asked RuntimeManager.search, got EngineClient.search).
        # Compare the dotted tail the caller specified: if they qualified it
        # (Class.method) check Class.method; if just a leaf, check the leaf.
        # Without this the agent can't tell a nearest-match from an exact hit.
        asked = str(t).split("::")[-1].split(":")[0].strip().strip(".").lower()
        got_sym = str(loc["symbol"]).strip().lower()
        asked_depth = asked.count(".") + 1
        got_tail = ".".join(got_sym.split(".")[-asked_depth:]) if asked else got_sym
        if asked and asked != got_tail:
            fuzzy.append(f"{t} -> {loc['file']}::{loc['symbol']}")
        key = (loc["file"], loc["symbol"])
        if key not in seen_sym:
            seen_sym.add(key)
            resolved.append(loc)
    if not resolved:
        return f"focus: could not resolve {', '.join(targets)} (give file::symbol or an exact name)"

    out = Out(int(a.get("budget_chars") or BUDGET["focus"]))
    multi = len(resolved) > 1
    hdr = (f"focus {len(resolved)} symbols in {len({r['file'] for r in resolved})} file(s)"
           if multi else f"focus {resolved[0]['file']}::{resolved[0]['symbol']}  "
           f"(lines {resolved[0]['start']}-{resolved[0]['end']})")
    out.add(hdr, force=True)
    if missing:
        out.add(f"(not resolved: {', '.join(missing)})", force=True)
    if fuzzy:
        out.add(f"(note: nearest match, exact name not found: {'; '.join(fuzzy)} "
                f"- confirm this is the symbol you meant)", force=True)

    want_bodies = a.get("include_bodies", True)
    # group by file so same-file symbols read together
    by_file: dict[str, list[dict]] = {}
    for loc in resolved:
        by_file.setdefault(loc["file"], []).append(loc)

    for rel, locs in by_file.items():
        if multi:
            out.add(f"=== {rel} ===", force=True)
        for loc in locs:
            sym = str(loc["symbol"]); name = sym.split(".")[-1]
            out.add(f"-- {rel}::{sym}  (lines {loc['start']}-{loc['end']}) --", force=True)
            if want_bodies:
                _pack_bodies(out, [{"file": rel, "symbol": sym,
                                    "start": loc["start"], "end": loc["end"]}])
            callers = _callers_of(name, rel, loc["start"], loc["end"])
            callees = _callees_in(rel, loc["start"], loc["end"])
            out.add("  wiring callers: " + ("; ".join(callers) if callers else "(none)"))
            out.add("  wiring calls:   " + ("; ".join(callees) if callees else "(none in repo)"))
        sibs = [str(s["symbol"]) for s in _top_level_symbols(rel)
                if str(s["symbol"]) not in {str(l["symbol"]) for l in locs}]
        if sibs:
            out.add(f"  siblings in {rel}: " + ", ".join(sibs[:20]))

    out.add("next: this is the code + wiring for ALL requested symbols - EDIT now. Do NOT focus/"
            "grep them again. To add another symbol, pass it in the SAME focus names=[...], not a new call.")
    return out.text()


def cfg_related(a: dict) -> str:
    """Given an ANCHOR chunk + a QUERY, return the code elsewhere that both relates
    to the anchor and matches the query, with bodies. One call replaces a grep
    chain starting from a chunk you already have."""
    anchor = str(a.get("anchor") or "").strip()
    query = str(a.get("query") or "").strip()
    if not anchor:
        return "error: related needs anchor=\"file::symbol\" (the chunk you have) and query=\"...\""
    loc = _locate_target(anchor)
    if "error" in loc:
        res = _resolve_symbol_name(anchor) if "::" not in anchor and ":" not in anchor else None
        if not res:
            return f"related: {loc['error']}"
        loc = res
    rel = loc["file"]
    sym = loc.get("symbol")
    name = str(sym).split(".")[-1] if sym else ""
    out = Out(int(a.get("budget_chars") or BUDGET["related"]))
    out.add(f"related to {_label(loc) if sym else rel}" + (f"  (query: {query})" if query else ""), force=True)

    # candidate set: semantic hits for (query + anchor name), plus the anchor's
    # callers/callees (structural relatedness), minus the anchor itself.
    sem_q = (query + " " + name).strip() or name
    cands: dict[tuple, dict] = {}

    def add(hrel, hln, source, boost=0.0):
        hrel = _norm(hrel)
        enc = _enclosing(hrel, hln)
        if not enc:
            return
        key = (hrel, enc["line"])
        if hrel == rel and sym and str(enc["symbol"]) == sym:
            return  # the anchor itself
        if key not in cands:
            cands[key] = {"file": hrel, "symbol": enc["symbol"], "start": enc["line"],
                          "end": enc["end_line"], "score": 0.0, "src": set()}
        cands[key]["score"] += boost
        cands[key]["src"].add(source)

    for i, h in enumerate(_search(sem_q, top_k=20)):
        add(h.get("path") or h.get("file"), int(h.get("start_line") or 1), "semantic",
            boost=1.0 - i * 0.03)
    if name:
        for cl in _callers_of(name, rel, loc.get("start", 0), loc.get("end", 0), cap=10):
            m = re.match(r"(.*?):(\d+)", cl)
            if m:
                add(m.group(1), int(m.group(2)), "caller", boost=0.6)
        for ce in _callees_in(rel, loc.get("start", 1), loc.get("end", 1), cap=10):
            m = re.match(r"(.*?):(\d+)", ce)
            if m:
                add(m.group(1), int(m.group(2)), "callee", boost=0.6)

    ranked = sorted(cands.values(), key=lambda c: -c["score"])
    ranked = [c for c in ranked if _in_scope(c["file"], a.get("scope") or "code")][:8]
    if not ranked:
        out.add("no related code found - broaden the query or check the anchor name")
        return out.text()
    out.add(f"{len(ranked)} related symbols (by relevance to anchor + query):", force=True)
    for c in ranked:
        out.add(f"  {_label(c)}  [{','.join(sorted(c['src']))}]")
    out.add("-- bodies --", force=True)
    _pack_bodies(out, ranked)
    out.add("next: these are the anchor-related symbols for your query - read/edit from here")
    return out.text()


def cfg_graph(a: dict) -> str:
    """Abstract JSON neighborhood: files -> top-level symbol names + call edges.
    No bodies. One wide, cheap orientation call."""
    query = str(a.get("query") or "").strip()
    anchor = str(a.get("anchor") or "").strip()
    out = Out(int(a.get("budget_chars") or BUDGET["graph"]))

    # seed files: anchor's file first, else the top semantic hits' files.
    seed_files: list[str] = []
    if anchor:
        loc = _locate_target(anchor)
        if "error" not in loc:
            seed_files.append(loc["file"])
    if query or not seed_files:
        for h in _search(query or anchor, top_k=18):
            rel = _norm(h.get("path") or h.get("file"))
            if rel.endswith(".py") and _kind_of(rel) == "code" and rel not in seed_files:
                seed_files.append(rel)
            if len(seed_files) >= 6:
                break
    seed_files = seed_files[:6]
    if not seed_files:
        return json.dumps({"error": "graph: no code files for query/anchor"})

    nodes = {}
    for rel in seed_files:
        syms = _top_level_symbols(rel)
        nodes[rel] = [str(s["symbol"]) for s in syms][:20]

    # edges: a symbol in one seed file that calls a top-level symbol defined in
    # ANOTHER seed file. Scan each symbol's body for `name(` where name is a
    # top-level symbol of a different seed file (cross-file call edges), plus
    # same-file calls so the shape is complete.
    name_to_file: dict[str, str] = {}
    for rel, syms in nodes.items():
        for s in syms:
            name_to_file.setdefault(s.split(".")[-1], rel)
    edges = []
    seen_edge = set()
    for rel, syms in nodes.items():
        for s in syms:
            so = next((x for x in _top_level_symbols(rel) if str(x["symbol"]) == s), None)
            if not so:
                continue
            body = _code_text(rel, so["line"] + 1, so["end_line"])
            for m in re.finditer(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)\s*\(", body):
                callee = m.group(1)
                tgt = name_to_file.get(callee)
                if not tgt or callee == s.split(".")[-1]:
                    continue
                e = (f"{rel}::{s}", f"{tgt}::{callee}")
                if e not in seen_edge:
                    seen_edge.add(e)
                    edges.append({"from": e[0], "to": e[1]})

    graph = {"query": query or None, "anchor": anchor or None,
             "nodes": [{"file": rel, "symbols": syms} for rel, syms in nodes.items()],
             "edges": edges[:40],
             "hint": "pick a node, then map config=focus names=[\"<file::symbol>\"] for its code+wiring"}
    text = json.dumps(graph, indent=1)
    if len(text) > out.budget:
        # drop edges first, then trim symbol lists
        graph["edges"] = graph["edges"][:15]
        text = json.dumps(graph, indent=1)
    return text


# ---------------------------------------------------------------------------
# tool dispatch + JSON-RPC
# ---------------------------------------------------------------------------

# CONFIGS = the ADVERTISED surface (schema enum, instructions, docs): find|focus only.
# HANDLERS = every handler that can still be SERVED. `related`/`graph` are kept as
# HIDDEN graceful fallbacks (v0.3.142 narrowed the surface to two) so a client/agent
# that still sends them is served + nudged toward find/focus, never hard-errored.
CONFIGS = ("find", "focus")
_HIDDEN_CONFIGS = {"related": cfg_related, "graph": cfg_graph}
HANDLERS = {"find": cfg_find, "focus": cfg_focus, **_HIDDEN_CONFIGS}


def tool_map(a: dict) -> str:
    cfg = str(a.get("config") or "find").strip().lower()
    try:
        if cfg in ("find", "focus"):
            return HANDLERS[cfg](a)
        # Hidden/retired configs degrade gracefully to the two-config surface.
        if cfg in ("graph",):
            return ("note: this build advertises config=find|focus only; 'graph' is folded into a "
                    "broad find. Serving via find.\n") + cfg_find(a)
        if cfg in ("related",):
            return ("note: this build advertises config=find|focus only; 'related' is folded into "
                    "find (put the anchor's names in the query). Serving via find.\n") + cfg_find(a)
        if cfg in ("view", "open", "outline"):
            return "note: configs are find|focus. For code use find/focus.\n" + cfg_find(a)
        if cfg in ("refs", "around"):
            return "note: wiring is folded into `focus`. Use config=focus names=[...].\n" + cfg_focus(a)
        return f"error: config must be one of {', '.join(CONFIGS)}"
    except Exception as e:  # noqa: BLE001
        return f"map {cfg} failed: {type(e).__name__}: {e}"


def tool_gate(_a: dict) -> str:
    return mv2.tool_gate(_a)


def tool_status(_a: dict) -> str:
    return mv2.tool_status(_a)


TOOLS = {
    "map": {"fn": tool_map,
            "description": ("Semantic code retrieval. config=find|focus. "
                            "find: where is X + code (also to orient a wide area with a broad query, "
                            "and to pull code near a chunk you hold). focus: a known symbol's code + "
                            "callers/callees + siblings in one unit. Partner to native Grep/Read."),
            "schema": {"type": "object", "properties": {
                "config": {"type": "string", "enum": list(CONFIGS)},
                "query": {"type": "string", "description": "semantic intent (find)"},
                "anchor": {"type": "string", "description": "a chunk you have: file::symbol | file:line (focus)"},
                "names": {"type": "array", "items": {"type": "string"}, "description": "exact identifiers (find/focus)"},
                "include_bodies": {"type": "boolean", "description": "focus returns full source (default true)"},
                "scope": {"type": "string", "description": "code|tests|docs|all (default code)"},
                "k": {"type": "integer"},
            }, "required": ["config"]}},
    "gate": {"fn": tool_gate, "description": "Health/managed signal only (not for finding code).",
             "schema": {"type": "object", "properties": {}}},
    "status": {"fn": tool_status, "description": "Engine health only; not for finding code.",
               "schema": {"type": "object", "properties": {}}},
}


def _send(o: dict) -> None:
    sys.stdout.write(json.dumps(o) + "\n"); sys.stdout.flush()


def main() -> int:
    import threading
    # Warm in the background so the user's first map call pays neither the whole-repo
    # file walk/read nor urllib's one-time ~350ms first-request init (the throwaway
    # /health inside _warm pre-pays it process-wide). The warm thread races only a
    # first call that arrives within ~1.5s of spawn; in practice the IDE handshake +
    # human gap lets it finish first. See scripts/perf/probe_startup*.py.
    threading.Thread(target=mv2._warm, name="map-v3-warm", daemon=True).start()
    # Idle keepalive: a periodic cheap re-warm so the first map call after an idle
    # gap (minutes) is still ms-fast. Keeps the worker's HTTP opener/socket live and
    # re-stamps the grep stat-TTL so a post-idle grep skips the per-file stat storm.
    # Interval defaults to 120s (well under any decay window; see the keepalive-
    # economics research note in docs/perf). Set CTX_MAP_WARM_INTERVAL_S=0 to disable.
    try:
        _warm_interval = float(os.environ.get("CTX_MAP_WARM_INTERVAL_S") or "120")
    except (TypeError, ValueError):
        _warm_interval = 120.0
    if _warm_interval > 0:
        threading.Thread(target=mv2._keepalive_loop, args=(_warm_interval,),
                         name="map-v3-keepalive", daemon=True).start()
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        method, rid = msg.get("method"), msg.get("id")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "scubiee-map-v3", "version": "1.0.0"},
                "instructions": SERVER_INSTRUCTIONS}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": n, "description": t["description"], "inputSchema": t["schema"]}
                for n, t in TOOLS.items()]}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            tool = TOOLS.get(params.get("name"))
            if not tool:
                _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown tool"}})
                continue
            mv2._LAST_CALL_AT[0] = time.time()  # mark active so keepalive stays idle-only
            try:
                res = tool["fn"](params.get("arguments") or {})
            except Exception as e:  # noqa: BLE001
                res = f"error: {type(e).__name__}: {e}"
            _send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": res}]}})
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif rid is not None:
            _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
