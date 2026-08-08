"""Agent-facing context toolkit: locate + related + snippet.

Philosophy (cheap INPUT vs expensive OUTPUT for the large model):
- First ask: ship a BIG map — how it works, where chunks live, related pieces.
- Follow-up: related(focus, question) / snippet — agent tweaks depth as needed.
- Do not starve the card; under-shipping causes Grep thrash (far costlier).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_JSON_RE = re.compile(r"\{[\s\S]*\}")

# Generous defaults — input is cheap; agent can lower via tool args
LOCATE_BUDGET = int(os.environ.get("CTX_LOCATE_BUDGET") or "28000")
RELATED_BUDGET = int(os.environ.get("CTX_RELATED_BUDGET") or "16000")
SNIPPET_MAX = int(os.environ.get("CTX_SNIPPET_MAX") or "4000")
EXCERPT_MAX = int(os.environ.get("CTX_EXCERPT_MAX") or "1600")

DISTILL_SYSTEM = """You write a HOW-IT-WORKS map for a coding agent. Reply ONLY JSON:
{
  "brief":"<4-8 sentences: end-to-end how this works for the user question; name the key files/symbols and how data/control flows>",
  "targets":[{"file":"...","start_line":0,"end_line":0,"role":"<entry|core|state|helper|other>","why":"<why this chunk matters>"}],
  "related_notes":["how A relates to B", "where state lives", "..."]
}
Rules:
- Use ONLY paths from the hits list. Never invent files.
- Prefer concrete modules over __init__.py.
- Max 6 targets, ordered entry → core → state/helpers.
- Brief must answer the user's question, not a generic theme."""


class _Cache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, tuple[float, dict[str, Any]]] = {}

    def ttl(self) -> float:
        try:
            return max(30.0, float(os.environ.get("CTX_LOCATE_CACHE_TTL_S") or "600"))
        except ValueError:
            return 600.0

    def key(self, *parts: Any) -> str:
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha1(raw.encode()).hexdigest()[:24]

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            hit = self._data.get(key)
            if not hit:
                return None
            ts, val = hit
            if time.time() - ts > self.ttl():
                self._data.pop(key, None)
                return None
            out = dict(val)
            out["cached"] = True
            out["cache_age_s"] = round(time.time() - ts, 2)
            return out

    def put(self, key: str, val: dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = (time.time(), dict(val))


_CACHE = _Cache()


def _norm(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def _repo(repo: Path | str | None) -> Path:
    p = Path(repo or os.environ.get("CTX_REPO") or ".").resolve()
    os.environ.setdefault("CTX_REPO", str(p))
    return p


def _is_weak(path: str | None) -> bool:
    if not path:
        return True
    return Path(str(path)).name.lower() in {"__init__.py", "__main__.py"}


def _query_tokens(q: str) -> set[str]:
    stop = {
        "the", "a", "an", "is", "are", "how", "does", "where", "what", "when",
        "and", "or", "to", "of", "in", "for", "with", "this", "that", "it",
        "be", "on", "at", "from", "as", "by", "can", "should", "want", "work",
        "works", "working", "figure", "out", "about", "into",
    }
    return {t for t in re.findall(r"[a-z0-9_]{3,}", q.lower()) if t not in stop}


def _path_query_score(path: str, tokens: set[str]) -> int:
    pl = path.lower().replace("\\", "/")
    score = 0
    for t in tokens:
        if t in pl:
            score += 3
        # stem-ish
        if t + ".py" in pl or f"/{t}/" in pl or pl.endswith(f"/{t}"):
            score += 2
    if _is_weak(path):
        score -= 5
    return score


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I).strip()
    cleaned = re.sub(r"```(?:json)?\s*([\s\S]*?)```", r"\1", cleaned).strip()
    m = _JSON_RE.search(cleaned)
    blob = m.group(0) if m else cleaned
    try:
        obj = json.loads(blob)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    if "{" in cleaned and "}" in cleaned:
        try:
            return json.loads(cleaned[cleaned.index("{") : cleaned.rindex("}") + 1])
        except json.JSONDecodeError:
            return None
    return None


def _search_hits(repo: Path, query: str, top_k: int = 10) -> list[dict[str, Any]]:
    from pipeline.context_agent.tools import tool_search_code

    out = tool_search_code(repo, query, top_k=top_k)
    tokens = _query_tokens(query)
    hits = []
    for h in out.get("hits") or []:
        f = h.get("file")
        hits.append(
            {
                "file": f,
                "start_line": h.get("start_line"),
                "end_line": h.get("end_line"),
                "score": h.get("score"),
                "why": (h.get("why") or "")[:200],
                "query_match": _path_query_score(str(f or ""), tokens),
            }
        )
    hits.sort(
        key=lambda h: (
            float(h.get("score") or 0.0) + 0.2 * float(h.get("query_match") or 0),
        ),
        reverse=True,
    )
    return hits


def _coerce_excerpt_text(blob: Any, max_chars: int) -> str:
    if blob is None:
        return ""
    if isinstance(blob, str):
        text = blob
    elif isinstance(blob, dict):
        inner = blob.get("text") or blob.get("span") or blob.get("content") or blob.get("code")
        if isinstance(inner, dict):
            inner = inner.get("text") or ""
        text = inner if isinstance(inner, str) else ""
    else:
        text = str(blob)
    text = text.strip()
    if len(text) > max_chars:
        return text[:max_chars] + "\n…[truncated]"
    return text


def _read_excerpt(
    repo: Path,
    path: str,
    start_line: int = 0,
    end_line: int = 0,
    max_chars: int = EXCERPT_MAX,
) -> dict[str, Any]:
    from pipeline.context_agent.tools import tool_read_span

    max_chars = max(200, min(int(max_chars or EXCERPT_MAX), SNIPPET_MAX))
    try:
        from pipeline.client import EngineClient
        from pipeline.daemon import ensure_daemon

        ensure_daemon(repo, force_if_hung=False)
        out = EngineClient().read_span(
            path,
            start_line=start_line or None,
            end_line=end_line or None,
            max_chars=max_chars,
            avoid=["figma", "seo", "dribbble"] if "figma" not in path.lower() else [],
            repo=str(repo),
        )
        if isinstance(out, dict):
            span = out.get("span") if isinstance(out.get("span"), dict) else out
            text = _coerce_excerpt_text(
                span if isinstance(span, dict) and "text" in span else (out.get("text") or out.get("span")),
                max_chars,
            )
            return {
                "ok": bool(out.get("ok", True)) and bool(text),
                "path": path,
                "start_line": (span or {}).get("start_line") if isinstance(span, dict) else start_line,
                "end_line": (span or {}).get("end_line") if isinstance(span, dict) else end_line,
                "excerpt": text,
            }
    except Exception:  # noqa: BLE001
        pass
    r = tool_read_span(repo, path, start_line, end_line, max_chars=min(max_chars, 700))
    text = _coerce_excerpt_text(r.get("text") or r, max_chars)
    return {
        "ok": bool(r.get("ok", True)) and bool(text),
        "path": path,
        "start_line": r.get("start_line") or start_line,
        "end_line": r.get("end_line") or end_line,
        "excerpt": text,
    }


def _heuristic_plan(query: str, hits: list[dict[str, Any]], max_targets: int = 6) -> dict[str, Any]:
    targets = []
    for h in hits:
        f = h.get("file")
        if not f or _is_weak(f):
            continue
        fl = str(f).lower()
        role = "core"
        if "session" in fl or "runtime" in fl:
            role = "entry"
        elif "store" in fl or "state" in fl or "persist" in fl:
            role = "state"
        elif "guidance" in fl or "lease" in fl:
            role = "core"
        targets.append(
            {
                "file": f,
                "start_line": int(h.get("start_line") or 0),
                "end_line": int(h.get("end_line") or 0),
                "role": role,
                "why": (h.get("why") or "")[:160],
            }
        )
        if len(targets) >= max_targets:
            break
    return {
        "brief": (
            f"Map for “{query[:120]}”. "
            "Targets are ordered retrieval hits with path-token boost; "
            "see related.siblings and related.graph for the wider neighborhood."
        ),
        "targets": targets,
        "related_notes": [
            "Follow targets top→bottom for the main path.",
            "Use related(focus=path, question=...) for follow-up links.",
        ],
        "distill": "heuristic",
    }


def _distill(query: str, hits: list[dict[str, Any]], max_targets: int = 6) -> dict[str, Any]:
    from pipeline.context_agent.llm_llama import LlamaCppClient

    client = LlamaCppClient(timeout=60.0, temperature=0.1, max_tokens=700)
    if not client.healthy():
        plan = _heuristic_plan(query, hits, max_targets=max_targets)
        plan["llama"] = "down"
        return plan

    raw = client.chat(
        [
            {"role": "system", "content": DISTILL_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"User question:\n{query}\n\nHits (ranked):\n"
                    + json.dumps(hits[:12], ensure_ascii=False)
                    + "\n\nReturn the how-it-works map JSON."
                ),
            },
        ]
    )
    obj = _extract_json(raw)
    if not obj or not isinstance(obj.get("targets"), list):
        plan = _heuristic_plan(query, hits, max_targets=max_targets)
        plan["distill"] = "parse_fallback"
        return plan

    allowed = {h.get("file") for h in hits if h.get("file")}
    targets = []
    for t in obj.get("targets") or []:
        if not isinstance(t, dict):
            continue
        f = t.get("file")
        if f not in allowed:
            continue
        targets.append(
            {
                "file": f,
                "start_line": int(t.get("start_line") or 0),
                "end_line": int(t.get("end_line") or 0),
                "role": str(t.get("role") or "other")[:40],
                "why": str(t.get("why") or "")[:180],
            }
        )
        if len(targets) >= max_targets:
            break
    if not targets:
        return _heuristic_plan(query, hits, max_targets=max_targets)

    notes = obj.get("related_notes") or []
    if not isinstance(notes, list):
        notes = []
    return {
        "brief": str(obj.get("brief") or "")[:1200],
        "targets": targets,
        "related_notes": [str(n)[:240] for n in notes[:10]],
        "distill": "qwen",
    }


def _graph_related(repo: Path, question: str, budget: int = 3500) -> str:
    try:
        from pipeline.context_agent.tools import tool_query_graph

        out = tool_query_graph(repo, question, token_budget=budget)
        text = out.get("text") or ""
        if len(text) > budget:
            text = text[:budget] + "\n…[truncated]"
        return text
    except Exception as exc:  # noqa: BLE001
        return f"(graph unavailable: {exc})"


def _trim_card(card: dict[str, Any], budget: int) -> dict[str, Any]:
    raw = json.dumps(card, default=str)
    if len(raw) <= budget:
        card["payload_chars"] = len(raw)
        return card
    # Soft shrink: graph first, then sibling whys, then excerpts
    rel = card.get("related")
    if isinstance(rel, dict) and rel.get("graph"):
        g = str(rel["graph"])
        while len(json.dumps(card, default=str)) > budget and len(g) > 600:
            g = g[: len(g) // 2] + "\n…[trimmed]"
            rel["graph"] = g
    for t in card.get("targets") or []:
        if len(json.dumps(card, default=str)) <= budget:
            break
        ex = t.get("excerpt") or ""
        if len(ex) > 400:
            t["excerpt"] = ex[: max(400, len(ex) // 2)] + "\n…[trimmed]"
    card["payload_chars"] = len(json.dumps(card, default=str))
    card["trimmed"] = True
    return card


# ── public API ──────────────────────────────────────────────────────────────


def locate(
    query: str,
    *,
    repo: Path | str | None = None,
    top_k: int = 12,
    mode: str = "map",
    max_targets: int = 0,
    excerpt_chars: int = 0,
    graph_budget: int = 0,
    use_distill: bool = False,
    with_excerpts: bool = True,
    with_graph: bool = True,
    touch_session: bool = True,
) -> dict[str, Any]:
    """First-ask / big retrieval. Default: CE-only (no LLM) — distill opt-in."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "empty query", "tool": "locate"}

    mode_s = (mode or "map").strip().lower()
    if mode_s not in {"map", "focus"}:
        mode_s = "map"

    # Savings-mode defaults (session-native 50% append target)
    try:
        from pipeline.session_store import savings_defaults as _sav

        sav = _sav(mode_s)
    except Exception:  # noqa: BLE001
        sav = {}

    if not max_targets:
        max_targets = int(sav.get("max_targets") or (6 if mode_s == "map" else 3))
    max_targets = max(2, min(int(max_targets), 8))

    if not excerpt_chars:
        excerpt_chars = int(
            sav.get("excerpt_chars")
            or (EXCERPT_MAX if mode_s == "map" else max(700, EXCERPT_MAX // 2))
        )
    excerpt_chars = max(300, min(int(excerpt_chars), SNIPPET_MAX))

    if not graph_budget:
        graph_budget = int(sav.get("graph_budget") or (4000 if mode_s == "map" else 1800))
    graph_budget = max(800, min(int(graph_budget), 8000))

    top_k = max(4, min(int(top_k or sav.get("top_k") or 12), 16))
    # Prefer env override for distill
    env_distill = os.environ.get("CTX_LOCATE_DISTILL", "").strip().lower()
    if env_distill in {"1", "true", "yes", "on"}:
        use_distill = True
    elif env_distill in {"0", "false", "no", "off"}:
        use_distill = False

    repo_p = _repo(repo)
    ck = _CACHE.key(
        "locate",
        repo_p,
        _norm(q),
        mode_s,
        top_k,
        max_targets,
        excerpt_chars,
        graph_budget,
        use_distill,
    )
    cached = _CACHE.get(ck)
    if cached is not None:
        return cached

    t0 = time.time()
    hits = _search_hits(repo_p, q, top_k=top_k)
    search_ms = round((time.time() - t0) * 1000)

    # focus mode: boost files already in the working heatmap
    if mode_s == "focus":
        try:
            from pipeline.work_session import heatmap as _hm

            hot = {h["file"]: h["heat"] for h in _hm(repo_p, top_n=30)}
            for h in hits:
                f = h.get("file")
                if f in hot:
                    h["query_match"] = int(h.get("query_match") or 0) + int(hot[f])
            hits.sort(
                key=lambda h: (
                    int(h.get("query_match") or 0),
                    float(h.get("score") or 0.0),
                ),
                reverse=True,
            )
        except Exception:  # noqa: BLE001
            pass

    t1 = time.time()
    plan = (
        _distill(q, hits, max_targets=max_targets)
        if (use_distill and hits)
        else _heuristic_plan(q, hits, max_targets=max_targets)
    )
    if not use_distill:
        plan["distill"] = "off"
    distill_ms = round((time.time() - t1) * 1000)

    hit_by_file = {h.get("file"): h for h in hits if h.get("file")}

    def _enrich(t: dict[str, Any]) -> dict[str, Any]:
        item = dict(t)
        h = hit_by_file.get(item.get("file")) or {}
        if not int(item.get("start_line") or 0) and h.get("start_line"):
            item["start_line"] = h.get("start_line")
        if not int(item.get("end_line") or 0) and h.get("end_line"):
            item["end_line"] = h.get("end_line")
        if not item.get("why") and h.get("why"):
            item["why"] = h.get("why")
        item["query_match"] = h.get("query_match") or _path_query_score(
            str(item.get("file") or ""), _query_tokens(q)
        )
        return item

    plan_targets = [_enrich(t) for t in (plan.get("targets") or [])]
    strong_hits = [h for h in hits if h.get("file") and not _is_weak(h.get("file"))]

    if strong_hits and all(_is_weak(t.get("file")) for t in plan_targets):
        plan_targets = [
            {
                "file": h["file"],
                "start_line": h.get("start_line") or 0,
                "end_line": h.get("end_line") or 0,
                "role": "core",
                "why": h.get("why") or "",
                "query_match": h.get("query_match") or 0,
            }
            for h in strong_hits[:max_targets]
        ]
    else:
        plan_targets = (
            [t for t in plan_targets if not _is_weak(t.get("file"))]
            + [t for t in plan_targets if _is_weak(t.get("file"))]
        )
        # Prefer higher query_match among strong
        plan_targets.sort(
            key=lambda t: (0 if _is_weak(t.get("file")) else 1, int(t.get("query_match") or 0)),
            reverse=True,
        )

    seen = {t.get("file") for t in plan_targets}
    for h in strong_hits:
        if len([t for t in plan_targets if not _is_weak(t.get("file"))]) >= max_targets:
            break
        f = h.get("file")
        if not f or f in seen:
            continue
        plan_targets.append(
            {
                "file": f,
                "start_line": h.get("start_line") or 0,
                "end_line": h.get("end_line") or 0,
                "role": "related",
                "why": h.get("why") or "",
                "query_match": h.get("query_match") or 0,
            }
        )
        seen.add(f)

    kept: list[dict[str, Any]] = []
    weak_kept = 0
    for t in plan_targets:
        if _is_weak(t.get("file")):
            if weak_kept >= 1:
                continue
            weak_kept += 1
        kept.append(t)
        if len(kept) >= max_targets:
            break
    plan_targets = kept

    t2 = time.time()
    targets_out = []
    for t in plan_targets:
        item = dict(t)
        if with_excerpts and item.get("file"):
            ex = _read_excerpt(
                repo_p,
                str(item["file"]),
                int(item.get("start_line") or 0),
                int(item.get("end_line") or 0),
                max_chars=excerpt_chars,
            )
            item["excerpt"] = ex.get("excerpt") or ""
            if not item["excerpt"]:
                # retry wider window
                ex = _read_excerpt(repo_p, str(item["file"]), 1, 80, max_chars=excerpt_chars)
                item["excerpt"] = ex.get("excerpt") or ""
            if ex.get("start_line"):
                item["start_line"] = ex["start_line"]
            if ex.get("end_line"):
                item["end_line"] = ex["end_line"]
            # drop empty-excerpt shells unless it's the only target
            if not item["excerpt"] and len(plan_targets) > 1:
                continue
        targets_out.append(item)
    if not targets_out and plan_targets:
        # keep at least one even if empty
        targets_out = [dict(plan_targets[0])]
    excerpt_ms = round((time.time() - t2) * 1000)

    target_files = {t.get("file") for t in targets_out}
    siblings = []
    for h in hits:
        f = h.get("file")
        if f and f not in target_files:
            siblings.append(
                {
                    "file": f,
                    "start_line": h.get("start_line"),
                    "end_line": h.get("end_line"),
                    "why": h.get("why"),
                    "query_match": h.get("query_match"),
                }
            )
        if len(siblings) >= (8 if mode_s == "map" else 4):
            break

    graph_text = ""
    graph_ms = 0
    if with_graph and hits:
        tg = time.time()
        graph_text = _graph_related(repo_p, q, budget=graph_budget)
        graph_ms = round((time.time() - tg) * 1000)

    card: dict[str, Any] = {
        "ok": True,
        "tool": "map" if mode_s == "map" else "focus",
        "mode": mode_s,
        "query": q,
        "brief": plan.get("brief") or "",
        "map": {
            "how_it_works": plan.get("brief") or "",
            "chunk_index": [
                {
                    "file": t.get("file"),
                    "start_line": t.get("start_line"),
                    "end_line": t.get("end_line"),
                    "role": t.get("role"),
                    "why": t.get("why"),
                }
                for t in targets_out
            ],
            "notes": plan.get("related_notes") or [],
        },
        "targets": targets_out,
        "files": [t["file"] for t in targets_out if t.get("file")],
        "related": {
            "notes": plan.get("related_notes") or [],
            "siblings": siblings,
            "graph": graph_text,
            "all_hits": [
                {
                    "file": h.get("file"),
                    "start_line": h.get("start_line"),
                    "end_line": h.get("end_line"),
                    "why": h.get("why"),
                    "query_match": h.get("query_match"),
                }
                for h in hits
            ],
        },
        "timing_ms": {
            "search": search_ms,
            "distill": distill_ms,
            "excerpts": excerpt_ms,
            "graph": graph_ms,
            "total": search_ms + distill_ms + excerpt_ms + graph_ms,
        },
        "distill": plan.get("distill"),
        "cached": False,
        "next": (
            "MAP: use brief + targets[].excerpt. "
            "Same topic for hours → workspace() then focus(query). "
            "New topic → map(query). Do NOT Grep/Glob."
            if mode_s == "map"
            else "FOCUS: hot-zone ask. workspace() for subgraph; map() for new topic. No Grep."
        ),
    }
    # Savings mode: agent pays for EVERY char. Drop dump fields TraceLab showed
    # agents never use (all_hits / fat graph / duplicate map index).
    savings = (os.environ.get("CTX_TOKEN_MODE") or "savings").lower() in {
        "savings",
        "save",
    }
    if savings:
        rel = card.get("related")
        if isinstance(rel, dict):
            rel.pop("all_hits", None)
            rel.pop("notes", None)  # duplicates next/brief
            sibs = rel.get("siblings") or []
            rel["siblings"] = [
                {"file": s.get("file"), "why": (s.get("why") or "")[:80]}
                for s in sibs[:3]
            ]
            # map already lists targets; skip graph novel unless tiny
            g = str(rel.get("graph") or "")
            if len(g) > 400:
                rel["graph"] = g[:400] + "\n…[trimmed]"
            if not rel.get("graph"):
                rel.pop("graph", None)
            if not rel.get("siblings"):
                rel.pop("siblings", None)
            if not rel:
                card.pop("related", None)
        # map.chunk_index duplicates targets after governor — keep thin pointers only
        mp = card.get("map")
        if isinstance(mp, dict):
            mp.pop("how_it_works", None)  # duplicate of brief
            idx = mp.get("chunk_index") or []
            mp["chunk_index"] = [
                {
                    "file": x.get("file"),
                    "start_line": x.get("start_line"),
                    "end_line": x.get("end_line"),
                    "handle": x.get("handle"),
                }
                for x in idx[:8]
            ]
        # Drop timing / meter noise from agent face
        card.pop("timing_ms", None)
        card.pop("payload_chars", None)
    if plan.get("llama"):
        card["llama"] = plan["llama"]

    if touch_session:
        try:
            from pipeline.work_session import touch as _touch

            _touch(
                repo_p,
                targets_out,
                query=q,
                weight=2 if mode_s == "map" else 1,
            )
        except Exception:  # noqa: BLE001
            pass

    # Session governor: store full excerpts server-side; return handles
    try:
        from pipeline.session_store import apply_governor_to_card, token_mode

        if os.environ.get("CTX_SESSION_GOVERNOR", "1").strip().lower() not in {
            "0",
            "false",
            "off",
            "no",
        }:
            card = apply_governor_to_card(repo_p, card)
            card["token_mode"] = token_mode()
    except Exception:  # noqa: BLE001
        pass

    # After governor, re-slim map index (it rewrites chunk_index with handles).
    if savings:
        mp = card.get("map")
        if isinstance(mp, dict):
            mp.pop("how_it_works", None)
            idx = mp.get("chunk_index") or []
            mp["chunk_index"] = [
                {
                    "file": x.get("file"),
                    "start_line": x.get("start_line"),
                    "end_line": x.get("end_line"),
                    "handle": x.get("handle"),
                    "status": x.get("status"),
                }
                for x in idx[:8]
            ]
        rel = card.get("related")
        if isinstance(rel, dict):
            rel.pop("all_hits", None)

    budget = LOCATE_BUDGET if mode_s == "map" else max(12000, LOCATE_BUDGET // 2)
    if savings:
        budget = min(budget, 6000 if mode_s == "map" else 4000)
    card = _trim_card(card, budget)
    # Do not cache governed cards across sessions in-process with full store coupling;
    # short TTL cache still ok for identical query bursts.
    _CACHE.put(ck, card)
    return card


def related(
    focus: str,
    *,
    repo: Path | str | None = None,
    question: str = "",
    to: str = "",
    graph_budget: int = 0,
    with_excerpts: bool = True,
) -> dict[str, Any]:
    """Follow-up: how does focus relate to neighbors / another path (to=...)."""
    focus_s = (focus or "").strip()
    if not focus_s:
        return {"ok": False, "error": "empty focus", "tool": "related"}

    repo_p = _repo(repo)
    to_s = (to or "").strip()
    q = (question or "").strip()
    if not q:
        if to_s:
            q = f"How does {focus_s} relate to {to_s}?"
        else:
            q = f"How does {focus_s} relate to callers, callees, and nearby modules?"

    gbudget = graph_budget or 4500
    gbudget = max(800, min(int(gbudget), 8000))

    ck = _CACHE.key("related", repo_p, _norm(focus_s), _norm(to_s), _norm(q), gbudget)
    cached = _CACHE.get(ck)
    if cached is not None:
        return cached

    t0 = time.time()
    search_q = f"{Path(focus_s).stem} {Path(to_s).stem if to_s else ''} {q}"[:240]
    hits = _search_hits(repo_p, search_q, top_k=10)
    graph = _graph_related(repo_p, f"{focus_s} {('vs ' + to_s) if to_s else ''}: {q}", budget=gbudget)

    neighbors = ""
    label = Path(focus_s).stem if ("/" in focus_s or "\\" in focus_s) else focus_s
    try:
        from pipeline.context_agent.tools import tool_get_neighbors

        neighbors = (tool_get_neighbors(repo_p, label).get("text") or "")[:3000]
    except Exception:  # noqa: BLE001
        neighbors = ""

    focus_excerpt = None
    to_excerpt = None
    if with_excerpts:
        if "/" in focus_s or "\\" in focus_s or focus_s.endswith(".py"):
            focus_excerpt = _read_excerpt(
                repo_p, focus_s.replace("\\", "/"), 1, 100, max_chars=EXCERPT_MAX
            )
        if to_s and ("/" in to_s or "\\" in to_s or to_s.endswith(".py")):
            to_excerpt = _read_excerpt(
                repo_p, to_s.replace("\\", "/"), 1, 100, max_chars=EXCERPT_MAX
            )

    # Small excerpts for top nearby hits
    nearby = []
    for h in hits[:6]:
        item = {
            "file": h.get("file"),
            "start_line": h.get("start_line"),
            "end_line": h.get("end_line"),
            "why": h.get("why"),
            "query_match": h.get("query_match"),
        }
        if with_excerpts and h.get("file") and not _is_weak(h.get("file")):
            ex = _read_excerpt(
                repo_p,
                str(h["file"]),
                int(h.get("start_line") or 1),
                int(h.get("end_line") or 0),
                max_chars=min(900, EXCERPT_MAX),
            )
            item["excerpt"] = ex.get("excerpt") or ""
        nearby.append(item)

    card: dict[str, Any] = {
        "ok": True,
        "tool": "related",
        "focus": focus_s,
        "to": to_s or None,
        "question": q,
        "map": {
            "graph": graph,
            "neighbors": neighbors,
            "nearby_hits": nearby,
        },
        "focus_excerpt": focus_excerpt,
        "to_excerpt": to_excerpt,
        "timing_ms": {"total": round((time.time() - t0) * 1000)},
        "cached": False,
        "next": (
            "Follow-up map ready. Answer from map + excerpts. "
            "Need more lines → snippet(...). New topic → locate(...). No Grep."
        ),
    }
    card = _trim_card(card, RELATED_BUDGET)
    _CACHE.put(ck, card)
    return card


def snippet(
    path: str,
    *,
    repo: Path | str | None = None,
    start_line: int = 0,
    end_line: int = 0,
    max_chars: int = 0,
) -> dict[str, Any]:
    """Pull a larger code window for a known path (agent-tweaked max_chars)."""
    path_s = (path or "").strip().replace("\\", "/")
    if not path_s:
        return {"ok": False, "error": "empty path", "tool": "snippet"}

    repo_p = _repo(repo)
    budget = max_chars or SNIPPET_MAX
    budget = max(200, min(int(budget), max(SNIPPET_MAX, 8000)))
    ex = _read_excerpt(repo_p, path_s, int(start_line or 0), int(end_line or 0), max_chars=budget)
    return {
        "ok": bool(ex.get("ok", True)),
        "tool": "snippet",
        "path": path_s,
        "start_line": ex.get("start_line"),
        "end_line": ex.get("end_line"),
        "excerpt": ex.get("excerpt") or "",
        "next": "Edit/answer from excerpt. Use locate for new topics; related for links.",
    }
