"""Single source of truth for node-ID normalization.

Three independent producers must agree on node IDs or the graph splits a single
entity into disconnected ghost nodes:

1. The AST extractor (``extract._make_id``) — deterministic, per-language.
2. The semantic subagents (LLM) — follow the node-ID spec in the skill prompt.
3. The graph builder (``build._normalize_id``) — reconciles edge endpoints when
   the LLM emits IDs with slightly different punctuation or casing than the AST.

Historically the normalization recipe was copy-pasted into ``extract._make_id``
and ``build._normalize_id`` and kept in sync only by mirrored docstrings, which
is exactly how the recurring ID-drift bug class crept in (#811 Unicode collapse,
#550 same-filename collisions, #1033 AST-vs-LLM file-node mismatch, #1104). This
module exists so the recipe lives in one place and the two callers can no longer
diverge.

The recipe: NFKC-normalize (so composed/decomposed Unicode forms collapse),
replace runs of non-word characters with a single underscore (``re.UNICODE`` so
CJK/Cyrillic/Arabic/accented-Latin letters survive instead of collapsing to a
per-file node), collapse repeated underscores, strip leading/trailing
underscores, and casefold.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

__all__ = ["normalize_id", "make_id"]

_NONWORD = re.compile(r"[^\w]+", re.UNICODE)
_UNDERS = re.compile(r"_+")


@lru_cache(maxsize=131072)
def normalize_id(s: str) -> str:
    r"""Normalize a single ID string to its canonical form.

    Idempotent: ``normalize_id(normalize_id(s)) == normalize_id(s)``.

    Cached: a whole-graph merge calls this ~114k times over ~16k nodes + 34k
    edges, but the ID strings repeat heavily (every edge endpoint re-normalizes a
    node ID). Memoizing the two-regex + NFKC recipe cut ~1s off ``build_from_json``.
    Pure and idempotent, so caching is safe; pre-compiled patterns avoid the
    ``re`` module's per-call cache lookup.
    """
    s = unicodedata.normalize("NFKC", s)
    s = _NONWORD.sub("_", s)
    s = _UNDERS.sub("_", s)
    return s.strip("_").casefold()


def make_id(*parts: str) -> str:
    """Build a canonical node ID from one or more name parts.

    Parts are joined with ``_`` (after stripping stray ``_``/``.`` edges from each
    part) and then run through :func:`normalize_id`, so the result is identical to
    what the builder produces from the joined string.
    """
    return normalize_id("_".join(p.strip("_.") for p in parts if p))
