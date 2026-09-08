"""Semantic index facade — Phase 0 wraps EmbedField; future multi-rep indexes.

Lineage contract: every vector maps back to a program node_id / file / loc
used by composite_v1 heatmaps. Invalidation keys (future): corpus fingerprint,
embedding model ID, representation version, chunking/index version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trace_lab.embed_field import EmbedField


@dataclass
class SemanticIndex:
    """Thin sensor over an embedding field keyed by heatmap node_id."""

    field: EmbedField
    representation: str = "code"  # future: behavior | dataflow | graph_context
    version: str = "v0"

    @property
    def backend(self) -> str:
        return getattr(self.field, "backend", "unknown")

    def query_affinities(self, query: str) -> dict[str, float]:
        return self.field.affinities(query)

    def seed_affinities(self, seed_id: str) -> dict[str, float]:
        """cos(seed, node) for all nodes in the field."""
        if seed_id not in self.field._by_id:  # noqa: SLF001
            return {nid: 0.0 for nid in self.field.ids}
        out: dict[str, float] = {}
        for nid in self.field.ids:
            out[nid] = float(self.field.pair_cos(seed_id, nid))
        return out

    def meta(self) -> dict[str, Any]:
        return {
            "representation": self.representation,
            "index_version": self.version,
            "embed_backend": self.backend,
            "n_vectors": len(self.field.ids),
        }


def from_embed_field(
    field: EmbedField,
    *,
    representation: str = "code",
    version: str = "v0",
) -> SemanticIndex:
    """Phase 0 constructor — reuse product/lab EmbedField matrices."""
    return SemanticIndex(field=field, representation=representation, version=version)
