"""CLI: enrich a repo — Graphify once → RepoIR → metadata-prepended chunks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "packages"))

from enrich import enrich_repo  # noqa: E402
from parse_harness.graphify_adapter import parse_with_graphify  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate graph-enriched code chunks")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--limit", type=int, default=0, help="Max chunks to write as samples (0=all in index)")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.exists():
        print(f"error: repo not found: {repo}", file=sys.stderr)
        return 2

    ir = parse_with_graphify(repo, parallel=False)
    enriched = enrich_repo(ir, repo)

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    samples = out / "samples"
    samples.mkdir(exist_ok=True)

    index = []
    original_chars = 0
    enriched_chars = 0
    for i, chunk in enumerate(enriched):
        original_chars += len(chunk.original)
        enriched_chars += len(chunk.enriched)
        entry = {
            "id": i,
            "file": chunk.file,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "symbol": chunk.symbol,
            "original_chars": len(chunk.original),
            "enriched_chars": len(chunk.enriched),
            "delta_chars": len(chunk.enriched) - len(chunk.original),
        }
        index.append(entry)

        write_sample = args.limit <= 0 or i < args.limit
        if write_sample:
            safe = chunk.file.replace("/", "__").replace("\\", "__")
            name = f"{i:04d}_{safe}_{chunk.symbol or 'preamble'}.txt"
            (samples / name).write_text(chunk.enriched, encoding="utf-8")

    summary = {
        "repo": str(repo),
        "parser": ir.parser,
        "chunk_count": len(enriched),
        "original_chars": original_chars,
        "enriched_chars": enriched_chars,
        "delta_chars": enriched_chars - original_chars,
        "delta_ratio": round((enriched_chars / original_chars), 4) if original_chars else None,
        "ir_stats": ir.stats,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    (out / "repo_ir.json").write_text(ir.canonical_json(structural_only=True), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
