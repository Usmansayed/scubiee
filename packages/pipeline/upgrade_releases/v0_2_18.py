"""Release 0.2.18 — index schema v2 (metadata stamp, compress_mode)."""

from __future__ import annotations

from pipeline.upgrade_registry import migrate_component, release

INDEX_SCHEMA = migrate_component(
    "index_schema",
    reason="schema v2: compress_mode metadata + schema_version stamp",
)


@release("0.2.18", notes="Index schema v2 — metadata-only migration for enrolled projects")
class Release_0_2_18:
    index_schema = INDEX_SCHEMA
