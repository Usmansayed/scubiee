"""Human-like query: map → pack(heatmap-only) → agent-needed reads → compare.

Stores full artifacts for usefulness of compressed heatmap vs what we'd Read.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/superpowers/plans/2026-09-06-heatmap-pack-vs-agent-reads.json"
OUT_MD = ROOT / "docs/superpowers/plans/2026-09-06-heatmap-pack-vs-agent-reads.md"

# Blind human-like task (no known file/symbol names).
CASE = {
    "id": "h01",
    "task": (
        "When I connect Scubiee to Cursor, I need to understand the full path "
        "that writes MCP config and permissions so the agent can call tools."
    ),
    "enrich_query": (
        "connect cursor install mcp config permissions allowlist autoApprove "
        "project rules gate text write tool surface so agent can call locate pack"
    ),
}

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _toks(s: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(s or "")}


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("./")


def _map_warm(query: str, *, k: int = 10) -> dict[str, Any]:
    from pipeline.searcher import search_repo

    t0 = time.perf_counter()
    hits = search_repo(ROOT, query, top_k=k, use_server=True) or []
    cards = []
    for i, h in enumerate(hits, 1):
        f = _norm(str(getattr(h, "file", None) or ""))
        cards.append(
            {
                "rank": i,
                "file": f,
                "symbol": getattr(h, "symbol", None) or "",
                "score": float(getattr(h, "score", 0) or 0),
                "loc": getattr(h, "loc", None) or f"{f}:1-1",
            }
        )
    return {"ok": bool(cards), "elapsed_s": round(time.perf_counter() - t0, 3), "cards": cards}


def _map_files(cards: list[dict[str, Any]], *, n: int = 5) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in cards:
        f = _norm(str(c.get("file") or ""))
        if not f.startswith("packages/") or not f.endswith(".py"):
            continue
        if f in seen:
            continue
        seen.add(f)
        out.append(f)
        if len(out) >= n:
            break
    return out


def _score_symbol(query: str, file: str, symbol: str, kind: str, text: str) -> float:
    q = _toks(query)
    name = (symbol or "").split(".")[-1]
    if not name or name in {"ROOT", "__init__"}:
        return -1e9
    priv = name.startswith("_") and not name.startswith("__")
    priv_pen = 4.0 if priv and name.lower() not in q else 0.0
    kind_bonus = {"function": 3.0, "method": 2.5, "class": 0.5}.get(kind, 0.0)
    name_l, sym_l = name.lower(), (symbol or "").lower()
    hit = 0.0
    for t in q:
        if t == name_l or t in name_l or name_l in t:
            hit += 3.0
        elif t in sym_l:
            hit += 1.5
        elif t in file.lower().replace("/", " ").replace("_", " "):
            hit += 0.2
    hit += 0.35 * len(q & _toks(text[:800]))
    return hit + kind_bonus - priv_pen


def _select_chunks(query: str, files: list[str], nodes: dict[str, Any], *, max_chunks: int = 3) -> list[dict[str, Any]]:
    cands: list[tuple[float, dict[str, Any]]] = []
    file_set = set(files)
    for n in nodes.values():
        f = n.file.replace("\\", "/")
        if f not in file_set or n.kind not in {"function", "method", "class"}:
            continue
        sc = _score_symbol(query, f, n.symbol, n.kind, n.text or "")
        if sc < -100:
            continue
        cands.append(
            (
                sc,
                {
                    "file": f,
                    "symbol": n.symbol,
                    "kind": n.kind,
                    "loc": f"{f}:{n.start_line}-{n.end_line}",
                    "start_line": n.start_line,
                    "end_line": n.end_line,
                    "score": round(sc, 3),
                },
            )
        )
    cands.sort(key=lambda x: (-x[0], x[1]["file"], x[1]["symbol"]))
    picked: list[dict[str, Any]] = []
    per_file: dict[str, int] = {}
    for _sc, ch in cands:
        f = ch["file"]
        if per_file.get(f, 0) >= 2:
            continue
        key = f"{f}::{ch['symbol']}"
        if any(f"{p['file']}::{p['symbol']}" == key for p in picked):
            continue
        picked.append(ch)
        per_file[f] = per_file.get(f, 0) + 1
        if len(picked) >= max_chunks:
            break
    return picked


def _pack_heatmap(query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    from pipeline.context_trace import run_pack_context
    from pipeline.mcp_response_lean import apply_lean_fields

    if not chunks:
        return {"ok": False, "error": "no_chunks"}
    c0 = chunks[0]
    c1 = chunks[1] if len(chunks) > 1 else None
    bits = " | ".join(f"{c['file']}::{c['symbol']}@{c['loc']}" for c in chunks)
    pack_q = f"{query}\nrelevant_chunks: {bits}"
    t0 = time.perf_counter()
    raw = run_pack_context(
        ROOT,
        pack_q,
        seed_file=c0["file"],
        seed_symbol=c0.get("symbol") or "",
        seed_line=int(c0.get("start_line") or 0),
        seed2_file=(c1 or {}).get("file") or "",
        seed2_symbol=(c1 or {}).get("symbol") or "",
        seed2_line=int((c1 or {}).get("start_line") or 0),
        mode="lean",
        policy="strict",
        k=16,
        engine="composite_v1",
        tool_name="pack_context",
        include_bodies=False,
        prior_packed_ids=set(),
    )
    slim = apply_lean_fields(dict(raw))
    slim["elapsed_s"] = round(time.perf_counter() - t0, 3)
    slim["_raw_n_heatmap"] = len(raw.get("heatmap") or [])
    slim["_raw_include_bodies"] = raw.get("include_bodies")
    # Ensure no body text leaked
    blob = json.dumps(slim)
    slim["_has_code_body"] = "def " in blob and "return" in blob
    return slim


def _parse_loc(loc: str) -> tuple[str, int | None, int | None]:
    loc = str(loc or "")
    if ":" not in loc:
        return "", None, None
    try:
        file, span = loc.rsplit(":", 1)
        a, b = span.split("-", 1)
        return _norm(file), int(a), int(b)
    except Exception:
        return _norm(loc.split(":")[0]), None, None


def _agent_needed_reads() -> list[dict[str, Any]]:
    """Spans a human agent would open to actually work the connect task."""
    return [
        {"file": "packages/pipeline/__main__.py", "start": 1706, "end": 1744, "why": "cmd_connect entry"},
        {"file": "packages/pipeline/rules_installer.py", "start": 1560, "end": 1640, "why": "install_tool fan-out"},
        {"file": "packages/pipeline/rules_installer.py", "start": 1487, "end": 1553, "why": "apply_connected_tools_to_repo"},
        {"file": "packages/pipeline/rules_installer.py", "start": 1312, "end": 1374, "why": "write_project_tool_surface"},
        {"file": "packages/pipeline/rules_installer.py", "start": 1139, "end": 1202, "why": "write_project_gate_rules"},
        {"file": "packages/pipeline/mcp_permissions.py", "start": 518, "end": 531, "why": "apply_permissions_to_repo_tool_surface"},
        {"file": "packages/pipeline/mcp_permissions.py", "start": 253, "end": 320, "why": "merge_cursor_permissions"},
    ]


def _load_span(file: str, start: int, end: int) -> tuple[str, int, int]:
    lines = (ROOT / file).read_text(encoding="utf-8", errors="replace").splitlines()
    s, e = max(1, start), min(len(lines), end)
    text = "\n".join(lines[s - 1 : e])
    return text, e - s + 1, len(text)


def _intersects(a0: int, a1: int, b0: int | None, b1: int | None) -> bool:
    if b0 is None or b1 is None:
        return False
    return not (a1 < b0 or b1 < a0)


def main() -> int:
    sys.path.insert(0, str(ROOT / "packages"))
    os.environ.setdefault("CTX_TRUST_ID_FILE", "1")
    os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
    os.environ.pop("CTX_MCP_PACK_BODIES", None)
    os.environ.pop("CTX_MCP_FULL_LOCATE", None)

    from pipeline.context_trace import _CACHE, _load_repo

    print("Loading nodes…", flush=True)
    nodes = _load_repo(ROOT).nodes
    _CACHE.clear()
    t0 = time.perf_counter()

    q = CASE["enrich_query"]
    print("[1] map…", flush=True)
    m = _map_warm(q, k=10)
    files = _map_files(m["cards"], n=5)
    chunks = _select_chunks(q, files, nodes, max_chunks=3)
    print(f"  files={files[:4]} chunks={[c['symbol'] for c in chunks]}", flush=True)

    print("[2] pack_context (heatmap-only)…", flush=True)
    pack = _pack_heatmap(q, chunks)
    heat = list(pack.get("heatmap") or [])
    print(
        f"  n_heatmap={len(heat)} read.top={pack.get('read', {}).get('top')} "
        f"has_code={pack.get('_has_code_body')} bytes={len(json.dumps(pack))}",
        flush=True,
    )

    print("[3] agent-needed reads…", flush=True)
    agent_specs = _agent_needed_reads()
    agent_loaded = []
    total_chars = 0
    for spec in agent_specs:
        text, nlines, chars = _load_span(spec["file"], spec["start"], spec["end"])
        total_chars += chars
        agent_loaded.append({**spec, "n_lines": nlines, "chars": chars, "text": text})

    # Compare agent spans vs heatmap (full + top-N recommended)
    top_n = int((pack.get("read") or {}).get("top") or 5)
    top_heat = heat[:top_n]
    covered_full = []
    covered_top = []
    missing = []
    for a in agent_loaded:
        hits_full = []
        hits_top = []
        for h in heat:
            f, s, e = _parse_loc(str(h.get("loc") or ""))
            if f != a["file"]:
                continue
            if _intersects(a["start"], a["end"], s, e):
                hits_full.append(h)
                if h in top_heat or h.get("r", 99) <= top_n:
                    hits_top.append(h)
        same_file = [h for h in heat if _parse_loc(str(h.get("loc") or ""))[0] == a["file"]]
        entry = {
            "agent": f"{a['file']}:{a['start']}-{a['end']}",
            "why": a["why"],
            "chars": a["chars"],
        }
        if hits_full:
            covered_full.append({**entry, "hits": hits_full})
            if hits_top:
                covered_top.append({**entry, "hits": hits_top})
            else:
                covered_top.append({**entry, "hits": "on_heatmap_but_below_read_top"})
        elif same_file:
            covered_full.append({**entry, "hits": "SAME_FILE_ONLY", "cards": same_file[:3]})
            covered_top.append({**entry, "hits": "SAME_FILE_ONLY"})
        else:
            missing.append(entry)

    n = len(agent_loaded)
    summary = {
        "heatmap_cards": len(heat),
        "pack_json_chars": len(json.dumps(pack)),
        "agent_read_chars": total_chars,
        "agent_spans": n,
        "span_cover_full_heatmap": round(len([c for c in covered_full if c["hits"] != "SAME_FILE_ONLY"]) / n, 3),
        "span_cover_read_top": round(len([c for c in covered_top if isinstance(c["hits"], list)]) / n, 3),
        "same_file_only": sum(1 for c in covered_full if c["hits"] == "SAME_FILE_ONLY"),
        "missing_from_heatmap": len(missing),
        "pack_has_code_bodies": bool(pack.get("_has_code_body")),
        "compression_vs_agent_reads": round(len(json.dumps(pack)) / max(total_chars, 1), 3),
    }

    doc = {
        "protocol": "heatmap_pack_vs_agent_reads_v1",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "scubiee_note": "pack MCP returns compressed heatmap only (0.3.24+)",
        "case": CASE,
        "map": m,
        "selected_chunks": chunks,
        "pack_mcp_view": pack,
        "agent_needed_reads": [
            {k: v for k, v in a.items() if k != "text"} | {"text_chars": a["chars"]}
            for a in agent_loaded
        ],
        "agent_needed_reads_full_text": agent_loaded,
        "compare": {
            "covered_full_heatmap": [
                {**c, "hits": c["hits"] if not isinstance(c["hits"], list) else [
                    {"r": h.get("r"), "heat": h.get("heat"), "loc": h.get("loc"), "s": h.get("s")}
                    for h in c["hits"]
                ]}
                for c in covered_full
            ],
            "covered_read_top": covered_top,
            "missing": missing,
            "summary": summary,
        },
    }
    OUT.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    lines = [
        "# Heatmap-only pack vs agent-needed reads",
        "",
        f"**Task:** {CASE['task']}",
        "",
        f"**Enrich:** `{CASE['enrich_query']}`",
        "",
        "## Summary",
        "",
        f"- Pack MCP JSON size: **{summary['pack_json_chars']}** chars (no code bodies: `{not summary['pack_has_code_bodies']}`)",
        f"- Agent would read: **{summary['agent_read_chars']}** chars across {n} spans",
        f"- Compression ratio (pack/agent): **{summary['compression_vs_agent_reads']}**",
        f"- Exact span cover (full heatmap): **{summary['span_cover_full_heatmap']}**",
        f"- Exact span cover (read.top={top_n}): **{summary['span_cover_read_top']}**",
        f"- Missing from heatmap: **{summary['missing_from_heatmap']}**",
        "",
        "## Pack heatmap (MCP view)",
        "",
    ]
    for h in heat[:12]:
        lines.append(
            f"- r={h.get('r')} heat={h.get('heat')} `{h.get('loc')}` `{h.get('s')}` sc={h.get('sc')}"
        )
    lines += ["", f"**read guidance:** {pack.get('read')}", "", "## Agent needed", ""]
    for a in agent_loaded:
        lines.append(f"- `{a['file']}:{a['start']}-{a['end']}` — {a['why']} ({a['chars']} chars)")
    lines += ["", "## Missing from heatmap", ""]
    for mspan in missing:
        lines.append(f"- `{mspan['agent']}` — {mspan['why']}")
    lines += ["", f"Full JSON: `{OUT.relative_to(ROOT).as_posix()}`", ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"wrote {OUT}")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
