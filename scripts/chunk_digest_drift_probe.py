"""Issue 5: why does the first edit after an upgrade re-embed the whole file?

Read-only. For each file: load its stored chunk records from chunks.jsonl, rebuild
them from the file on disk exactly the way a sync does (extract -> repo IR ->
chunk_file_from_ir -> inject_metadata -> compress), and diff per chunk key with
the same ``diff_chunk_records`` the sync uses. Unedited files should show 0
changed; anything else would be re-embedded by the next save of that file.
Prints the first differing line pair per changed chunk.

    python scripts/chunk_digest_drift_probe.py <repo> <rel> [<rel> ...]
"""

from __future__ import annotations

import difflib
import json
import os
import sys
import tempfile
from pathlib import Path


def rebuild(root: Path, rel: str, meta: dict, max_chars: int = 1200):
    from enrich import chunk_file_from_ir, inject_metadata
    from graphify.extract import extract
    from parse_harness.graphify_adapter import graphify_to_repo_ir

    from pipeline.chunk_compress import compress_chunk, resolve_compress_mode
    from pipeline.store import ChunkRecord

    tmp = Path(tempfile.mkdtemp(prefix="drift_"))
    raw = extract([root / rel], root=root, cache_root=tmp)
    ir = graphify_to_repo_ir(raw, root=root, elapsed_ms=0.0, file_count=1)
    out = []
    cmode = resolve_compress_mode(meta.get("compress_mode"))
    cmax = int(meta.get("compress_max_chars") or os.environ.get("CTX_COMPRESS_MAX_CHARS", "512"))
    for ch in chunk_file_from_ir(ir, root, rel):
        body = inject_metadata(ch, ir).enriched
        if cmode:
            body = compress_chunk(body, cmode, max_chars=cmax).text
            cap = cmax
        else:
            body = body[:max_chars]
            cap = max_chars
        body = body.lstrip("\ufeff") if isinstance(body, str) else body
        out.append(ChunkRecord(id=-1, file=ch.file, start_line=ch.start_line, end_line=ch.end_line,
                               symbol=ch.symbol, text=(ch.content or "").lstrip("\ufeff")[:cap],
                               enriched=body))
    return out


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    rels = [r.replace("\\", "/") for r in sys.argv[2:]]
    from pipeline.chunk_merkle import chunk_digest, chunk_key, diff_chunk_records
    from pipeline.project_id import peek_project
    from pipeline.store import ChunkRecord

    ref = peek_project(root)
    meta = json.loads((ref.store_dir / "meta.json").read_text(encoding="utf-8"))
    stored: dict[str, list[ChunkRecord]] = {r: [] for r in rels}
    with (ref.store_dir / "chunks.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            f = str(row.get("file") or "").replace("\\", "/")
            if f in stored:
                stored[f].append(ChunkRecord(**row))
    total_changed = 0
    for rel in rels:
        new = rebuild(root, rel, meta)
        diff = diff_chunk_records(stored[rel], new)
        total_changed += len(diff.changed)
        print(f"{rel}: stored={len(stored[rel])} rebuilt={len(new)} changed={len(diff.changed)} "
              f"unchanged={len(diff.unchanged)} removed={len(diff.removed)}")
        old_by = {chunk_key(c): c for c in stored[rel]}
        shown = 0
        for c in new:
            k = chunk_key(c)
            if k not in diff.changed or shown >= 3:
                continue
            o = old_by.get(k)
            if o is None:
                print(f"  [{k}] new key (no stored chunk)")
                shown += 1
                continue
            d = [x for x in difflib.unified_diff((o.enriched or "").splitlines(), (c.enriched or "").splitlines(),
                                                 lineterm="", n=0) if x[:1] in "+-" and x[:3] not in ("+++", "---")]
            print(f"  [{k}] digest {chunk_digest(o)[:8]} -> {chunk_digest(c)[:8]}; first diff lines:")
            for x in d[:4]:
                print(f"      {x[:160]}")
            shown += 1
    print(f"\nTOTAL changed chunks across {len(rels)} unedited file(s): {total_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
