"""Static + optional runtime probe of Claude Context's AST role.

Claude Context uses tree-sitter only for chunk boundaries (AstCodeSplitter).
It does not build a symbol table, import graph, or call graph.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ClaudeContextCapabilities:
    parser: str = "tree-sitter (via AstCodeSplitter)"
    extracts_symbols: bool = False
    extracts_imports: bool = False
    extracts_exports: bool = False
    extracts_call_graph: bool = False
    produces_chunks: bool = True
    languages_ast: tuple[str, ...] = (
        "javascript",
        "typescript",
        "python",
        "java",
        "cpp",
        "go",
        "rust",
        "csharp",
        "scala",
    )
    notes: str = (
        "AST walk emits text chunks for SPLITTABLE_NODE_TYPES only. "
        "No named symbols / imports / call edges. Unsupported langs fall back to LangChain splitter."
    )
    source_file: str = (
        "(historical) Claude Context AstCodeSplitter — not vendored; "
        "product uses Graphify extract + packages/pipeline Merkle sync"
    )


def probe_claude_context(repo_root: Path | None = None) -> dict:
    """Return capability report. Optional repo_root reserved for future chunk counting."""
    caps = ClaudeContextCapabilities()
    report = asdict(caps)
    report["repo_root"] = str(repo_root.resolve()) if repo_root else None
    report["structural_ir_support"] = False
    report["role_in_final_architecture"] = (
        "Keep for chunking/embedding/retrieval only; do not use as structure parser."
    )
    return report
