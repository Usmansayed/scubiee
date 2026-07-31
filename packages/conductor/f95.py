"""F95 lexical bridges: stem, role alias, package siblings, negation demotion.

Deterministic (no LLM). Used by MultiArchConductor.retrieve_F_f95.
"""

from __future__ import annotations

import re
from pathlib import Path

from conductor.bm25_index import tokenize

_CAMEL = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|\d+")

# Bidirectional morphology / synonym bridges for code IR
_STEM_MAP: dict[str, set[str]] = {
    "distilled": {"distill", "distillation"},
    "distillation": {"distill", "distilled"},
    "distill": {"distilled", "distillation"},
    "validates": {"validate", "validation", "validator"},
    "validate": {"validates", "validation", "validator"},
    "validation": {"validate", "validates", "validator"},
    "persists": {"persist", "persisting"},
    "persist": {"persists", "persisting"},
    "traces": {"trace", "tracing"},
    "trace": {"traces", "tracing"},
    "scoring": {"score", "scorer", "scores"},
    "score": {"scoring", "scorer", "scores"},
    "recording": {"record", "recorder", "records"},
    "record": {"recording", "recorder", "records"},
    "records": {"record", "recorder", "recording"},
    "replay": {"replayed", "replaying"},
}

# Query cues that imply a *Recorder / persist-trace role
ROLE_TRIGGERS = frozenset(
    {
        "persist",
        "persists",
        "persisting",
        "store",
        "stores",
        "stored",
        "trace",
        "traces",
        "tracing",
        "replay",
        "replayed",
        "record",
        "records",
        "recording",
        "recorder",
    }
)

ROLE_BASENAME_HINTS = frozenset({"recorder"})

_NEG_PHRASE = re.compile(
    r"\bnot\s+(?:the\s+)?([a-z0-9_\-/]+(?:\s+[a-z0-9_\-/]+){0,4})",
    re.IGNORECASE,
)
_NEG_STOP = frozenset(
    {
        "the",
        "a",
        "an",
        "itself",
        "for",
        "later",
        "than",
        "vs",
        "versus",
        "or",
        "and",
        "of",
        "to",
        "in",
        "on",
        "with",
        "from",
        "that",
        "this",
        "those",
        "these",
        "not",
        "but",
        "into",
        "over",
        "under",
        "about",
        "human",
        "facing",
        "machine",
        "readable",
        "per",
        "tool",
        "implementations",
        "prompt",
        "text",
        "pydantic",
        "models",
        "claim",
        "validators",
        "null",
    }
)

_HUB_STEMS = frozenset({"__init__", "workflows", "scorer"})


def path_tokens(path: str) -> set[str]:
    p = path.replace("\\", "/").lower()
    parts = re.split(r"[/_.\-]+", p)
    out: set[str] = set()
    for part in parts:
        if len(part) < 2:
            continue
        out.add(part)
        out.update(t.lower() for t in _CAMEL.findall(part) if len(t) > 1)
    return out


def query_key_tokens(query: str) -> set[str]:
    toks = set(tokenize(query))
    for m in _CAMEL.findall(query):
        if len(m) > 1:
            toks.add(m.lower())
    for frag in re.findall(r"[A-Za-z0-9_./\-]+\.py", query):
        toks |= path_tokens(frag)
    return {t for t in toks if len(t) > 1}


def expand_stems(toks: set[str]) -> set[str]:
    """Morphology + synonym bridge (distilled ↔ distillation, …)."""
    out = set(toks)
    for t in list(toks):
        if t in _STEM_MAP:
            out |= _STEM_MAP[t]
        # light suffix peel for stems not in map
        for suf in ("ed", "ing", "ion", "ions", "er", "ers", "es", "s"):
            if t.endswith(suf) and len(t) - len(suf) >= 4:
                stem = t[: -len(suf)]
                out.add(stem)
                if stem in _STEM_MAP:
                    out |= _STEM_MAP[stem]
    return out


def negated_phrases(query: str) -> list[list[str]]:
    """Content-token lists for each 'not (the) …' span."""
    phrases: list[list[str]] = []
    for m in _NEG_PHRASE.finditer(query):
        phrase = m.group(1).lower()
        parts = [
            raw.strip("-")
            for raw in re.split(r"[\s_/]+", phrase)
            if raw.strip("-") and len(raw.strip("-")) >= 3 and raw.strip("-") not in _NEG_STOP
        ]
        if parts:
            phrases.append(parts)
    return phrases


def negated_tokens(query: str) -> set[str]:
    """Backward-compatible flat set (heads only); prefer negated_phrases for scoring."""
    out: set[str] = set()
    for parts in negated_phrases(query):
        heads = parts[-2:] if len(parts) >= 2 else parts
        for t in heads:
            out.add(t)
            out |= _STEM_MAP.get(t, set())
    return out


def role_boost(qtoks: set[str], path: str) -> float:
    """Boost *Recorder files when query has persist/trace/store/replay cues."""
    if not (qtoks & ROLE_TRIGGERS):
        return 0.0
    bn = Path(path).stem.lower()
    pt = path_tokens(path)
    if any(h in bn or h in pt for h in ROLE_BASENAME_HINTS):
        return 6.0
    if "record" in bn and bn != "recording":
        return 3.0
    return 0.0


def negation_multiplier(path: str, phrases: list[list[str]]) -> float:
    """Package-aware demotion: 'not the coordination … harness' ≠ all harnesses."""
    if not phrases:
        return 1.0
    pl = path.replace("\\", "/").lower()
    pt = path_tokens(path)
    bn = Path(path).stem.lower()
    parts_list = Path(pl).parts
    pl_flat = pl.replace("/", "_")

    for parts in phrases:
        heads = {parts[-1]}
        if len(parts) >= 2:
            heads.add(parts[-2])
        quals = [p for p in parts if p not in heads] or parts[:-1]
        head_hit = bn in heads or any(h in pt for h in heads)
        if not head_hit and not any(t in pt for t in parts if len(t) >= 5):
            continue

        if quals:
            lead = quals[0]
            lead_hit = lead in pt or any(lead in p for p in parts_list)
            # Only package-style bigrams among qualifiers (not validation_harness)
            bigram_hit = False
            if len(quals) >= 2:
                bigram_hit = any(
                    "_".join(quals[i : i + 2]) in pl_flat for i in range(len(quals) - 1)
                )
            if head_hit and (lead_hit or bigram_hit):
                return 0.12
            if head_hit and not lead_hit and not bigram_hit:
                continue
            if not head_hit and (lead_hit or bigram_hit):
                return 0.45
        elif head_hit:
            return 0.18
    return 1.0


# Distinctive path segments worth force-injecting when present in expanded query toks
_PATH_INJECT_HINTS = frozenset(
    {
        "distillation",
        "recorder",
        "perception_runtime",
        "browser_validator",
        "browser_session_manager",
        "coordination_score",
        "tool_catalog",
        "crg_impl",
        "null_impl",
    }
)


def path_hint_files(qtoks: set[str], all_files: list[str]) -> list[str]:
    hints = qtoks & _PATH_INJECT_HINTS
    out: list[str] = []
    seen: set[str] = set()
    for f in all_files:
        fk = f.replace("\\", "/")
        pt = path_tokens(fk)
        hit = bool(hints and hints & pt) or len(qtoks & pt) >= 3
        if hit and fk not in seen:
            out.append(fk)
            seen.add(fk)
    return out


def hub_multiplier(path: str, qtoks: set[str], phrases: list[list[str]] | None = None) -> float:
    """Demote package hubs when persist/trace role cues are active."""
    if not (qtoks & ROLE_TRIGGERS):
        return 1.0
    bn = Path(path).stem.lower()
    if bn in _HUB_STEMS or bn.startswith("run_"):
        return 0.35
    if bn == "harness":
        # If a negation phrase targets this package's harness, demote hard
        if phrases:
            nm = negation_multiplier(path, phrases)
            if nm < 0.5:
                return nm
        if "harness" in qtoks:
            return 1.0
        return 0.45
    return 1.0


def package_key(path: str) -> str:
    p = path.replace("\\", "/")
    return str(Path(p).parent)


def sibling_files(seed_files: list[str], all_files: list[str]) -> list[str]:
    """All corpus files sharing a parent dir with any seed."""
    wanted = {package_key(f) for f in seed_files}
    out: list[str] = []
    seen: set[str] = set()
    for f in all_files:
        fk = f.replace("\\", "/")
        if package_key(fk) in wanted and fk not in seen:
            out.append(fk)
            seen.add(fk)
    return out
