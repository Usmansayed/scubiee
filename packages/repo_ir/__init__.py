"""Canonical repository intermediate representation for graph-aware chunk enrichment.

One parse pass (Graphify) emits RepoIR. Downstream chunk metadata and (later)
Claude Context embedding only consume this schema — they must not re-parse ASTs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Relation = Literal[
    "contains",
    "imports",
    "imports_from",
    "re_exports",
    "calls",
    "inherits",
    "implements",
    "method",
]


@dataclass(frozen=True)
class Symbol:
    id: str
    name: str
    kind: str  # file | function | class | method | interface | type | other
    file: str
    line: int | None = None


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    relation: str
    confidence: str = "EXTRACTED"
    file: str | None = None


@dataclass
class FileIR:
    path: str
    symbols: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)


@dataclass
class RepoIR:
    """Deterministic structural view of a repository."""

    root: str
    parser: str
    files: dict[str, FileIR]
    symbols: dict[str, Symbol]
    edges: list[Edge]
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "parser": self.parser,
            "files": {k: asdict(v) for k, v in sorted(self.files.items())},
            "symbols": {k: asdict(v) for k, v in sorted(self.symbols.items())},
            "edges": [asdict(e) for e in sorted(self.edges, key=lambda e: (e.relation, e.source, e.target))],
            "stats": self.stats,
        }

    def to_structural_dict(self) -> dict[str, Any]:
        """IR without volatile fields (timing) — used for determinism checks."""
        data = self.to_dict()
        stats = dict(data.get("stats") or {})
        stats.pop("elapsed_ms", None)
        data["stats"] = stats
        return data

    def canonical_json(self, *, structural_only: bool = False) -> str:
        import json

        payload = self.to_structural_dict() if structural_only else self.to_dict()
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
