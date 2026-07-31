"""Deterministic query typing for D vs C routing (no LLM).

path_likeness ∈ [0,1]:
  high → identifier / path / terse (favor D_rerank / A)
  low  → natural-language paraphrase (favor C_gear)

Features are surface-form only — no gold-set keywords.
"""

from __future__ import annotations

import re

from conductor.bm25_index import tokenize
from conductor.f95 import query_key_tokens

_FUNC = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "from",
        "into",
        "that",
        "which",
        "who",
        "where",
        "when",
        "what",
        "how",
        "why",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "these",
        "those",
        "it",
        "its",
        "as",
        "by",
        "at",
        "not",
        "no",
        "than",
        "then",
        "so",
        "if",
        "else",
        "when",
        "while",
        "about",
        "over",
        "under",
        "after",
        "before",
        "between",
        "without",
        "within",
        "should",
        "would",
        "could",
        "can",
        "will",
        "does",
        "do",
        "did",
        "has",
        "have",
        "had",
        "used",
        "using",
        "use",
        "via",
        "per",
        "vs",
        "versus",
        "itself",
        "themselves",
    }
)

_CAMEL = re.compile(r"[A-Z][a-z]+[A-Z]")
_PATHISH = re.compile(r"[A-Za-z0-9_./\\-]+\.py|/|\\")


def path_likeness(query: str) -> float:
    """Score how path/identifier-like a query is. Clipped to [0, 1]."""
    q = query.strip()
    toks = tokenize(q)
    keys = query_key_tokens(q)
    s = 0.35  # prior: slightly toward blend

    if _PATHISH.search(q):
        s += 0.40
    snake = sum(1 for t in keys if "_" in t)
    s += min(0.35, 0.11 * snake)
    if _CAMEL.search(q):
        s += 0.12

    n = max(len(toks), 1)
    if n <= 4:
        s += 0.28  # terse / symbol-ish
    elif n <= 7:
        s += 0.08
    elif n >= 14:
        s -= 0.22  # long NL paraphrase
    elif n >= 10:
        s -= 0.12

    func_ratio = sum(1 for t in toks if t in _FUNC) / n
    s -= 0.35 * func_ratio

    # Explicit disambiguation language → semantic specialist (C)
    ql = q.lower()
    if " not " in f" {ql} " or " — not " in ql or " - not " in ql:
        s -= 0.12

    return float(max(0.0, min(1.0, s)))


def route_mode(query: str) -> str:
    """Hard route label: 'D' | 'C' | 'blend'.

    C is reserved for *clearly* NL paraphrase (low path_likeness). Diverse-domain
    technical paraphrases still look somewhat code-ish — prefer D/blend there.
    """
    p = path_likeness(query)
    if p >= 0.50:
        return "D"
    if p <= 0.28:
        return "C"
    return "blend"


def query_state(query: str) -> str:
    """Coarse retrieval state for Conductor-X router.

    SYMBOL — identifier/path/terse → D precision, no graph floor
    SOFT   — long NL / function words → dual-seed expand + gated floor
    BLEND  — middle → D + stricter gated floor only
    """
    p = path_likeness(query)
    if p >= 0.45:
        return "SYMBOL"
    if p <= 0.35:
        return "SOFT"
    return "BLEND"


def lexical_graph_confidence(query: str, file_path: str) -> float:
    """How grounded a Graphify hit is in query surface tokens (not embeddings)."""
    from conductor.f95 import path_tokens

    # Light domain synonyms (auth/secrets) — not gold-set specific filenames
    _SYN = {
        "key": ("token", "secret", "credential", "auth"),
        "keys": ("token", "secret", "credential", "auth"),
        "authentication": ("auth", "token", "credential"),
        "password": ("secret", "credential", "token"),
        "login": ("auth", "session"),
    }

    qtoks = query_key_tokens(query)
    if not qtoks:
        return 0.0
    ftoks = path_tokens(file_path)
    path_l = file_path.replace("\\", "/").lower()
    bn = path_l.rsplit("/", 1)[-1]
    stem = bn[:-3] if bn.endswith(".py") else bn
    score = float(len(qtoks & ftoks))
    if stem in qtoks:
        score += 2.0
    elif any(len(t) >= 4 and (t in stem or stem in t) for t in qtoks):
        score += 1.0
    for t in qtoks:
        if len(t) < 4:
            continue
        if t in path_l or t in stem.replace("_", ""):
            score += 1.0
            continue
        if t.endswith("s") and len(t) >= 5 and t[:-1] in path_l:
            score += 1.0
            continue
        for syn in _SYN.get(t, ()):
            if syn in path_l or syn in ftoks:
                score += 1.0
                break
    return score
