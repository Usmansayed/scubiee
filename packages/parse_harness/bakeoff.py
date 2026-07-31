"""AST bake-off: Graphify structural IR vs Claude Context chunking capabilities."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from parse_harness.claude_context_probe import probe_claude_context
from parse_harness.graphify_adapter import parse_with_graphify
from repo_ir import RepoIR


def run_bakeoff(repo_root: Path, *, out_dir: Path | None = None) -> dict:
    repo_root = repo_root.resolve()
    ir = parse_with_graphify(repo_root, parallel=False)
    cc = probe_claude_context(repo_root)

    winner = "graphify"
    rationale = (
        "Graphify produces deterministic symbols, imports, and call/contains edges from one "
        "tree-sitter pass. Claude Context's AstCodeSplitter only yields chunk text spans and "
        "cannot supply RepoIR without a second overlapping parser."
    )

    report = {
        "repo": str(repo_root),
        "winner_parser": winner,
        "rationale": rationale,
        "single_parse_rule": "Production path must call Graphify once and feed RepoIR downstream; Claude Context must not re-parse for structure.",
        "graphify": ir.stats | {"parser": ir.parser, "root": ir.root},
        "claude_context": cc,
        "overlap": {
            "both_use_tree_sitter": True,
            "duplicate_in_production": False,
            "keep": {
                "structure": "graphify",
                "chunking_embeddings_retrieval": "claude-context",
            },
        },
    }

    if out_dir is not None:
        out_dir = out_dir.resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "repo_ir.json").write_text(ir.canonical_json(), encoding="utf-8")
        (out_dir / "bakeoff.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return report


def assert_deterministic(repo_root: Path) -> tuple[RepoIR, RepoIR]:
    a = parse_with_graphify(repo_root, parallel=False)
    b = parse_with_graphify(repo_root, parallel=False)
    if a.canonical_json(structural_only=True) != b.canonical_json(structural_only=True):
        raise AssertionError("RepoIR differed across two Graphify parses of the same tree")
    return a, b
