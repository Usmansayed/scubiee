"""Estimate tokens for retrieval paths (baseline vs Context Engine).

No LLM calls — measures bytes/tokens that would enter agent context from
search/locate results vs naive grep+full-file reads.
"""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


def estimate_tokens(text: str) -> int:
    """Prefer tiktoken; else ~4 chars/token (Claude-ish)."""
    if not text:
        return 0
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, math.ceil(len(text) / 4))


@dataclass
class ArmResult:
    name: str
    query: str
    chars: int
    tokens: int
    ms: float
    hits: int
    files_touched: int
    payload_preview: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class QueryCompare:
    query: str
    baseline: ArmResult
    context_engine: ArmResult

    @property
    def tokens_saved(self) -> int:
        return max(0, self.baseline.tokens - self.context_engine.tokens)

    @property
    def pct_saved(self) -> float:
        if self.baseline.tokens <= 0:
            return 0.0
        return round(100.0 * self.tokens_saved / self.baseline.tokens, 1)


def _payload_tokens(obj: Any) -> tuple[int, int, str]:
    text = json.dumps(obj, ensure_ascii=False, indent=2) if not isinstance(obj, str) else obj
    return len(text), estimate_tokens(text), text[:400]


def baseline_grep_read(
    root: Path,
    query: str,
    *,
    max_files: int = 12,
    max_chars_per_file: int = 8000,
) -> ArmResult:
    """Naive agent path: token-ish grep → read whole matching files into context."""
    t0 = time.perf_counter()
    terms = [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)]
    terms = [t for t in terms if t not in {"the", "and", "for", "how", "what", "where", "with"}]
    if not terms:
        terms = [query.lower()[:40]]

    scored: dict[str, int] = {}
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if any(
            x in rel.lower()
            for x in (
                "/vendor/",
                "node_modules",
                ".venv",
                "site-packages",
                "/references/",
                "/research/",
                "graphify-out",
                "__pycache__",
            )
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low = text.lower()
        score = sum(low.count(t) for t in terms[:8])
        if score > 0:
            scored[rel] = score

    top = sorted(scored, key=lambda r: -scored[r])[:max_files]
    blobs: list[str] = []
    for rel in top:
        try:
            body = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        blobs.append(f"===== {rel} =====\n{body[:max_chars_per_file]}")
    payload = "\n\n".join(blobs)
    chars, toks, preview = _payload_tokens(payload)
    return ArmResult(
        name="baseline_grep_read",
        query=query,
        chars=chars,
        tokens=toks,
        ms=(time.perf_counter() - t0) * 1000,
        hits=len(top),
        files_touched=len(top),
        payload_preview=preview,
        detail={"terms": terms[:8], "files": top},
    )


def context_engine_arm(
    engine: Any,
    query: str,
    *,
    top_k: int = 8,
    prefer_locate: bool = True,
) -> ArmResult:
    """CE path: capability locate and/or search_code-style compact hits."""
    t0 = time.perf_counter()
    payload: dict[str, Any] = {"query": query, "hits": []}
    files: set[str] = set()

    if prefer_locate and hasattr(engine, "locate_capability"):
        caps = engine.locate_capability(query, top_k=top_k) or []
        for h in caps:
            payload["hits"].append(
                {
                    "path": h.path,
                    "symbol": h.symbol,
                    "why": (h.why or "")[:160],
                    "score": round(float(h.score), 3),
                    "source": "capability",
                }
            )
            files.add(h.path)

    # Always add compact search hits (may short-circuit embed on SOFT+cap)
    hits = engine.search(query, top_k=top_k, skip_freshness=True)
    for h in hits:
        files.add(h.file)
        payload["hits"].append(
            {
                "path": h.file,
                "score": round(float(h.score), 3),
                "why": (h.preview or "")[:160],
                "source": h.source,
            }
        )
    payload["timings"] = getattr(engine, "_last_timings", {})
    # Dedup hits by path keeping first
    seen: set[str] = set()
    dedup = []
    for row in payload["hits"]:
        p = row["path"]
        if p in seen:
            continue
        seen.add(p)
        dedup.append(row)
    payload["hits"] = dedup[:top_k]

    chars, toks, preview = _payload_tokens(payload)
    return ArmResult(
        name="context_engine",
        query=query,
        chars=chars,
        tokens=toks,
        ms=(time.perf_counter() - t0) * 1000,
        hits=len(payload["hits"]),
        files_touched=len(files),
        payload_preview=preview,
        detail={"retrieve_mode": (payload.get("timings") or {}).get("retrieve_mode")},
    )


def compare_queries(
    root: Path,
    engine: Any,
    queries: list[str],
    *,
    top_k: int = 8,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    base_tok = ce_tok = 0
    base_ms = ce_ms = 0.0
    for q in queries:
        b = baseline_grep_read(root, q)
        c = context_engine_arm(engine, q, top_k=top_k)
        cmp = QueryCompare(query=q, baseline=b, context_engine=c)
        base_tok += b.tokens
        ce_tok += c.tokens
        base_ms += b.ms
        ce_ms += c.ms
        rows.append(
            {
                "query": q,
                "baseline_tokens": b.tokens,
                "ce_tokens": c.tokens,
                "tokens_saved": cmp.tokens_saved,
                "pct_saved": cmp.pct_saved,
                "baseline_ms": round(b.ms, 1),
                "ce_ms": round(c.ms, 1),
                "baseline_files": b.files_touched,
                "ce_files": c.files_touched,
                "ce_mode": c.detail.get("retrieve_mode"),
            }
        )
    saved = max(0, base_tok - ce_tok)
    return {
        "root": str(root),
        "n_queries": len(queries),
        "baseline_tokens_total": base_tok,
        "ce_tokens_total": ce_tok,
        "tokens_saved_total": saved,
        "pct_saved_total": round(100.0 * saved / base_tok, 1) if base_tok else 0.0,
        "baseline_ms_total": round(base_ms, 1),
        "ce_ms_total": round(ce_ms, 1),
        "rows": rows,
    }
