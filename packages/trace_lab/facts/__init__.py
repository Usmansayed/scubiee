"""Typed fact / frontier edges for the semantic tracer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EdgeRel = str
EdgeSource = Literal["ast", "jedi", "graphify", "dfg", "cfg", "dispatch"]



@dataclass(frozen=True)
class TypedEdge:
    source: str
    target: str
    relation: EdgeRel
    weight: float
    confidence: EdgeSource = "ast"


STRUCTURAL = frozenset(
    {"CALLS", "CALLED_BY", "IMPORTS", "CONTAINS", "OVERRIDES", "DISPATCHES", "calls", "uses", "contains", "dispatches", "overrides", "imports", "called_by"}
)
DATA = frozenset(
    {"PASSES_DATA_TO", "READS", "WRITES", "PRODUCES", "CONSUMES", "uses"}
)
CONTROL = frozenset({"CONTROLS", "GUARDS"})
