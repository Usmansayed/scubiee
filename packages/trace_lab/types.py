"""Context-tracing simulation types.

A heatmap is a scored set of symbol-level nodes. Gold cases label which of
those nodes an agent actually needs (must), may need (should), or must not
treat as hot (must_not).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def node_id(file: str, symbol: str) -> str:
    return f"{file.replace(chr(92), '/')}::{symbol}"


@dataclass(frozen=True)
class TraceNode:
    id: str
    file: str
    symbol: str
    kind: str
    start_line: int
    end_line: int
    text: str
    lex_text: str = ""

    @property
    def token_count(self) -> int:
        return max(len((self.lex_text or self.text).split()), 1)

    @property
    def line_span(self) -> tuple[int, int]:
        return (self.start_line, self.end_line)


@dataclass(frozen=True)
class TraceEdge:
    source: str
    target: str
    relation: str
    weight: float


@dataclass
class HeatCell:
    node_id: str
    score: float
    why: str
    path: tuple[str, ...] = ()
    relation: str = ""


@dataclass
class Heatmap:
    strategy: str
    cells: list[HeatCell]
    extra: dict[str, Any] = field(default_factory=dict)

    def by_id(self) -> dict[str, HeatCell]:
        return {c.node_id: c for c in self.cells}

    def ranked_ids(self) -> list[str]:
        return [c.node_id for c in sorted(self.cells, key=lambda c: -c.score)]

    def hot_ids(self, threshold: float) -> list[str]:
        return [c.node_id for c in self.cells if c.score >= threshold]


@dataclass(frozen=True)
class GoldRef:
    file: str
    symbol: str
    why: str = ""

    @property
    def id(self) -> str:
        return node_id(self.file, self.symbol)


@dataclass
class GoldCase:
    id: str
    title: str
    query: str
    seed: GoldRef
    must: list[GoldRef]
    should: list[GoldRef]
    must_not: list[GoldRef]
    gold_rank: list[str]
    notes: str = ""

    @property
    def must_ids(self) -> set[str]:
        return {r.id for r in self.must}

    @property
    def should_ids(self) -> set[str]:
        return {r.id for r in self.should}

    @property
    def must_not_ids(self) -> set[str]:
        return {r.id for r in self.must_not}

    @property
    def relevant_ids(self) -> set[str]:
        return self.must_ids | self.should_ids
