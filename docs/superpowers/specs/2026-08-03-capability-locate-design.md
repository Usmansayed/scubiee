# Capability locate — design

**Date:** 2026-08-03  
**Status:** implement  
**Goal:** Soft suite 10/10 + fast non-RAG locate without LLM tokens.

## Architecture

```text
Query
  ├─ SYMBOL / path-like / exact → grep_code | symbol   (pointer)
  ├─ SOFT intent-like           → capability cards     (pointer)
  └─ else / enrich              → R_plan RAG           (compact hits)
Explicit MCP: locate_capability | grep_code | file_outline | search_code
```

No LLM in card build or locate. Cards from docstrings + symbols + path + deterministic intent expansions from concepts *present in the docstring*.

## Card schema

See `pipeline.capability.CapabilityCard`. Persisted as `capability_cards.json` under the pipeline store.

## Router

- SOFT + strong card hit → prefer capability pointers (merge ahead of RAG).
- SYMBOL / high path_likeness → grep/symbol-style path still via RAG BM25-lead; grep tool available explicitly.
- Else R_plan.

## Success

- Soft 10/10, hard 4/4, locate warm ≪ RAG, default payloads pointer-sized.
