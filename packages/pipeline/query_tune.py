"""Generic soft-query polish — no codebase knowledge.

Mirrors production: user types something vague; an assistant that does *not*
know your repo rewrites it a little clearer for search. No Merkle / FastEmbed
/ keeper injection — only ordinary English cleanup + search framing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TunedQuery:
    soft: str
    tuned: str
    notes: list[str]

    def to_dict(self) -> dict:
        return {"soft": self.soft, "tuned": self.tuned, "notes": self.notes}


# Casual → slightly clearer (language only, not product terms)
_CASUAL: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bwhats\b", re.I), "what is"),
    (re.compile(r"\bwhere's\b", re.I), "where is"),
    (re.compile(r"\bhows\b", re.I), "how is"),
    (re.compile(r"\bwheres\b", re.I), "where is"),
    (re.compile(r"\bdont\b", re.I), "do not"),
    (re.compile(r"\bdoesn't\b", re.I), "does not"),
    (re.compile(r"\bcan't\b", re.I), "cannot"),
    (re.compile(r"\bwont\b", re.I), "will not"),
    (re.compile(r"\bi'm\b", re.I), "I am"),
    (re.compile(r"\bi\b"), "I"),
]


def _normalize_spaces(s: str) -> str:
    s = s.replace("—", "-").replace("–", "-")
    return " ".join(s.split()).strip()


def _fix_casual(s: str) -> tuple[str, list[str]]:
    notes: list[str] = []
    out = s
    for pat, repl in _CASUAL:
        nxt = pat.sub(repl, out)
        if nxt != out:
            notes.append(f"casual→{repl!r}")
            out = nxt
    return out, notes


def _frame_as_code_question(s: str) -> tuple[str, list[str]]:
    """Light search framing without naming modules/files in this repo."""
    notes: list[str] = []
    low = s.lower()

    # Already looks like a clear question
    if low.startswith(
        ("how does", "how do", "where is", "where are", "what is", "what are", "why does", "why would")
    ):
        framed = s
        if not framed.endswith("?"):
            framed = framed.rstrip(".!") + "?"
            notes.append("add ?")
        return framed, notes

    # "where do we X" → "Where in the code do we X?"
    m = re.match(r"where do we (.+)$", s, re.I)
    if m:
        notes.append("frame where-do-we")
        return f"Where in the code do we {m.group(1).rstrip('?')}?", notes

    # "how do we X" → "How does the code X?"
    m = re.match(r"how do we (.+)$", s, re.I)
    if m:
        notes.append("frame how-do-we")
        return f"How does the code {m.group(1).rstrip('?')}?", notes

    # "what picks / what happens" keep, ensure question mark
    if re.match(r"what (picks|happens|calls|handles)\b", s, re.I):
        notes.append("frame what-")
        q = s[0].upper() + s[1:] if s else s
        if not q.endswith("?"):
            q += "?"
        return q, notes

    # Generic: treat as "find code about …"
    notes.append("frame find-code-about")
    body = s.rstrip("?.!")
    return f"Find code about: {body}?", notes


def tune_query(soft: str) -> TunedQuery:
    """Polish vague user text a little — as if you don't know this repo."""
    soft = _normalize_spaces(soft)
    if not soft:
        return TunedQuery(soft="", tuned="", notes=[])

    notes: list[str] = []
    s, n1 = _fix_casual(soft)
    notes.extend(n1)
    # Drop filler without adding domain knowledge
    s2 = re.sub(r"\b(kinda|sort of|basically|like)\b", "", s, flags=re.I)
    s2 = _normalize_spaces(s2)
    if s2 != s:
        notes.append("drop filler")
        s = s2

    tuned, n2 = _frame_as_code_question(s)
    notes.extend(n2)
    # Capitalize first letter
    if tuned and tuned[0].islower():
        tuned = tuned[0].upper() + tuned[1:]
        notes.append("capitalize")

    return TunedQuery(soft=soft, tuned=tuned, notes=notes)


def load_soft_queries(path: str | Path) -> list[str]:
    lines: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines
