"""CLI locate ladder: map → pack → expand (same engines as MCP; lean JSON for agents)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from pipeline.mcp_response_lean import slim_locate_payload


def _root(path: str | Path | None) -> Path:
    return Path(path or ".").expanduser().resolve()


def _env_flag(name: str) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def cli_full_enabled(*, full: bool | None = None) -> bool:
    """Full debug payload when ``--full`` or ``CTX_CLI_FULL=1``."""
    if full is True:
        return True
    if full is False:
        return False
    return _env_flag("CTX_CLI_FULL")


def slim_cli_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """CLI agent view — same slim locate payload as MCP default."""
    return slim_locate_payload(payload)


def emit_cli_json(payload: dict[str, Any], *, full: bool | None = None) -> None:
    """Print CLI JSON. Default: slim + compact. ``--full`` / CTX_CLI_FULL=1 keeps chrome."""
    use_full = cli_full_enabled(full=full)
    body = payload if use_full else slim_cli_payload(payload)
    if use_full:
        print(json.dumps(body, indent=2, ensure_ascii=False, default=str))
    else:
        # Compact: agents should read pack[].text / cards / cold locs — not pretty chrome.
        print(
            json.dumps(
                body,
                ensure_ascii=False,
                default=str,
                separators=(",", ":"),
            )
        )


def _dump(payload: dict[str, Any]) -> None:
    """Deprecated alias — prefer emit_cli_json."""
    emit_cli_json(payload)


def cli_map(
    query: str,
    *,
    path: str | Path = ".",
    k: int = 10,
    local: bool = False,
) -> dict[str, Any]:
    """Soft locate cards + suggested_seed (no bodies). Next: scubiee pack."""
    from pipeline.context_trace import fill_map_card_symbol, pick_suggested_seed
    from pipeline.searcher import SearchEngineError, search_repo

    root = _root(path)
    q = (query or "").strip()
    if not q:
        return {"ok": False, "tool": "map", "error": "query required"}
    t0 = time.perf_counter()
    try:
        hits = search_repo(
            root,
            q,
            top_k=max(1, min(int(k), 30)),
            use_server=not local,
        )
    except SearchEngineError:
        hits = search_repo(
            root,
            q,
            top_k=max(1, min(int(k), 30)),
            use_server=False,
        )
    cards: list[dict[str, Any]] = []
    for h in hits:
        file = str(getattr(h, "file", "") or "").replace("\\", "/")
        role = "docs"
        low = file.lower()
        if "/test" in f"/{low}" or low.startswith("tests/") or low.endswith("_test.py"):
            role = "test"
        elif (
            file.startswith("packages/")
            or file.startswith("src/")
            or file.startswith("app/")
        ) and low.endswith((".py", ".ts", ".tsx", ".js", ".go", ".rs")):
            role = "function"
        elif low.endswith((".md", ".txt", ".rst")) or "/docs/" in f"/{low}" or low in {
            "agents.md",
            "readme.md",
        }:
            role = "docs"
        else:
            role = "other"
        start = int(getattr(h, "start_line", None) or 0) or 1
        end = int(getattr(h, "end_line", None) or 0) or start
        preview = (getattr(h, "preview", None) or "")[:180]
        cards.append(
            fill_map_card_symbol(
                {
                    "rank": getattr(h, "rank", len(cards) + 1),
                    "file": file,
                    "score": getattr(h, "score", 0),
                    "chunk_id": getattr(h, "chunk_id", None),
                    "why": preview,
                    "preview": preview,
                    "role": role,
                    "start_line": start,
                    "end_line": end,
                    "loc": f"{file}:{start}-{end}",
                    "symbol": "",
                    "kind": "function" if role == "function" else "chunk",
                }
            )
        )
    suggested = pick_suggested_seed(cards)
    if suggested is None:
        # Prefer packages/ code cards over docs/tests even if pick_suggested_seed abstains
        for c in cards:
            f = str(c.get("file") or "").replace("\\", "/")
            if c.get("role") == "function" or f.startswith(("packages/", "src/", "app/")):
                if f.lower().endswith((".md", ".txt", ".rst")):
                    continue
                suggested = {
                    "file": f,
                    "symbol": str(c.get("symbol") or ""),
                    "start_line": int(c.get("start_line") or 1),
                    "loc": c.get("loc"),
                    "kind": c.get("kind") or "chunk",
                    "role": c.get("role") or "other",
                    "score": c.get("score"),
                }
                break
    if suggested is None and cards:
        top = cards[0]
        suggested = {
            "file": top.get("file"),
            "symbol": str(top.get("symbol") or ""),
            "start_line": int(top.get("start_line") or 1),
            "loc": top.get("loc"),
            "kind": top.get("kind") or "chunk",
            "role": top.get("role") or "other",
            "score": top.get("score"),
        }
    return {
        "ok": True,
        "tool": "map",
        "query": q,
        "k": int(k),
        "count": len(cards),
        "cards": cards,
        "suggested_seed": suggested,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        "ladder": "scubiee map → scubiee pack --mode lean → scubiee expand",
        "next": (
            "scubiee pack \"{q}\" --seed-file {f} --mode lean".format(
                q=q.replace('"', '\\"'),
                f=(suggested or {}).get("file") or "<from cards>",
            )
            if suggested
            else "Pick a packages/ card file, then scubiee pack — refine the expanded query with card/seed names."
        ),
        "query_tip": (
            "Expand vague asks into ~30–80 tokens of denser code vocabulary "
            "(symbols, paths, APIs, verbs, error strings) before map/pack; "
            "refine with new names after map/expand."
        ),
    }


def cli_pack(
    query: str,
    *,
    seed_file: str,
    path: str | Path = ".",
    seed_symbol: str = "",
    seed_line: int = 0,
    mode: str = "lean",
    policy: str = "strict",
    k: int = 16,
) -> dict[str, Any]:
    """Tracer/heatmap + hot bodies. Requires seed_file from map or known path."""
    from pipeline.context_trace import run_pack_context

    root = _root(path)
    q = (query or "").strip()
    seed = (seed_file or "").strip().replace("\\", "/")
    if not q:
        return {"ok": False, "tool": "pack", "error": "query required"}
    if not seed:
        return {
            "ok": False,
            "tool": "pack",
            "error": "seed_file required",
            "hint": "Run scubiee map first and pass suggested_seed.file",
        }
    t0 = time.perf_counter()
    out = run_pack_context(
        root,
        q,
        seed_file=seed,
        seed_symbol=seed_symbol or "",
        seed_line=int(seed_line or 0),
        mode=(mode or "lean").strip().lower() or "lean",
        policy=(policy or "strict").strip().lower() or "strict",
        k=max(1, min(int(k), 32)),
    )
    out = {k: v for k, v in out.items() if not str(k).startswith("_")}
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out["cli"] = "pack"
    out["query_tip"] = (
        "Keep/refine the expanded code-vocab query from map (add card/seed names); do not shrink to a vague phrase."
    )
    if out.get("ok"):
        out["next_cli"] = (
            "Read pack[] then cold card.loc spans. If thin: "
            "scubiee expand --node <heatmap id> --direction callees --with-bodies"
        )
    return out


def cli_expand(
    *,
    node: str,
    path: str | Path = ".",
    query: str = "",
    direction: str = "callees",
    with_bodies: bool = False,
    k: int = 10,
) -> dict[str, Any]:
    """Delta heatmap from a pack/map node. Prefer after lean pack when a hop is missing."""
    from pipeline.context_trace import run_expand_context

    root = _root(path)
    nid = (node or "").strip()
    if not nid:
        return {"ok": False, "tool": "expand", "error": "node required (heatmap id)"}
    t0 = time.perf_counter()
    out = run_expand_context(
        root,
        node=nid,
        query=(query or "").strip(),
        direction=(direction or "callees").strip().lower() or "callees",
        with_bodies=bool(with_bodies),
        k=max(1, min(int(k), 32)),
    )
    out = {k: v for k, v in out.items() if not str(k).startswith("_")}
    out["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    out["cli"] = "expand"
    return out
