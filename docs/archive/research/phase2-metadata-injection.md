# Phase 2–3 — Metadata Generation & Injection

Date: 2026-07-31

## Decision (from Phase 1)

- **One parse:** Graphify → `RepoIR`
- **Chunks:** symbol-span slices from `RepoIR` line anchors + file text (no second AST)
- **Injection:** prepend concise metadata; boundaries unchanged
- **Not yet:** embeddings, Milvus, retrieval A/B (Phase 4)

## Metadata fields (lightweight)

| Field | Source |
|-------|--------|
| Repository | `RepoIR.root` basename |
| Module | top-level path segment |
| Folder | parent directory |
| File | relative path |
| Functions | callables whose start line falls in chunk span |
| Imports | file-level import symbols/modules |
| Exports | file-level exported callables |
| Related Files | sibling files in same folder (cap 8) |
| Immediate Dependents | files that import this file/symbols (1 hop, cap 8) |

Avoided: full graph dump, multi-hop neighbors, LLM text.

## Injection format

```
Repository: ...
Module: ...
Folder: ...
File: ...

Functions:
- ...

Imports:
- ...

Exports:
- ...

Graph Context:
- Parent Folder: .../
- Related Files:
    - ...
- Immediate Dependents:
    - ...

--------------------------------

(original chunk)
```

## Evidence (`scubiee-news-flow`)

| Metric | Value |
|--------|-------|
| Chunks | 144 |
| Original chars | 202,321 |
| Enriched chars | 292,248 |
| Delta | +89,927 (~1.44×) |

```text
pytest tests → 9 passed
python -m enrich testdata/scubiee-news-flow --out out/scubiee-enrich --limit 5
```

## Packages

- `packages/metadata` — `build_chunk_meta` / `ChunkMeta.render`
- `packages/enrich` — `chunk_repo_from_ir` / `inject_metadata` / `enrich_repo`

## Next (Phase 4)

Wire enriched text into Claude Context embedding path; keep vanilla index for A/B recall metrics.
