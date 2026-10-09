# Phase 1 — Parser & Overlap Comparison

Date: 2026-07-31  
Test corpus: `fixtures/mini-repo` + `testdata/scubiee-news-flow`  
Scope: AST / structural extraction only (no embeddings, no semantic/LLM passes)

## Executive decision

| Concern | Keep | Drop / do not duplicate |
|--------|------|-------------------------|
| Structural AST (symbols, imports, calls) | **Graphify** (tree-sitter) | Claude Context must not grow a parallel symbol/import extractor |
| Chunking + embeddings + retrieval | **Claude Context** | Do not replace with GraphRAG |
| File change detection | Decide in Phase 2 (CC Merkle sync vs Graphify watch/cache) | Avoid two live watchers |

**Single-parse rule:** Production indexing calls Graphify once → `RepoIR` → metadata prepend → Claude Context chunk/embed/retrieve. Claude Context may still walk ASTs for *chunk boundaries* only until chunk bounds are derived from `RepoIR` (optional later optimization). Structure must not be parsed twice.

Bake-off winner: **`graphify`** (`out/scubiee/bakeoff.json`).

---

## Parsing

| | Claude Context | Graphify |
|--|----------------|----------|
| Parser | tree-sitter (native Node) | tree-sitter (Python) |
| Babel / tsc | Not used for AST | Not used for code AST |
| Role | `AstCodeSplitter` — chunk boundaries | Full structural extract + resolve |
| Languages (AST) | ~9 (JS/TS, Py, Java, C/C++, Go, Rust, C#, Scala); else LangChain fallback | ~36 grammars; TS/TSX first-class |
| Incremental parse cache | No AST cache; Merkle file hashes for reindex | AST content-hash cache under `graphify-out/cache` |
| Speed (scubiee-news-flow) | N/A for IR (no IR) | ~3.3s cold-ish extract → 553 symbols, 841 edges |

**Remain as structure parser:** Graphify.

---

## Repository index

| Capability | Claude Context | Graphify | Stronger |
|------------|----------------|----------|----------|
| Symbol extraction | No (text spans only) | Yes (file/class/function/…) | Graphify |
| AST as IR | Chunk list only | nodes + edges | Graphify |
| Imports / exports | No | `imports`, `imports_from`, `re_exports` | Graphify |
| Call graph | No | `calls` / `indirect_call` (+ EXTRACTED/INFERRED) | Graphify |
| Dependency / inherits | No | `extends`, `implements`, `references`, … | Graphify |

On `scubiee-news-flow` (Graphify): 76 files, 70 callables, 155 imports, 227 imports_from, 34 calls.

---

## File watching

| | Claude Context | Graphify |
|--|----------------|----------|
| Mechanism | Merkle DAG + `reindexByChange`; MCP trigger/`fs.watch` | `graphify watch` (watchdog) + `update` + manifest |
| Cache invalidation | File hash → re-split/embed changed files | AST cache by content hash + extractor version |

**Phase 1 choice:** keep both as *libraries*; production should use **one** invalidation driver later (prefer Claude Context’s sync if it owns indexing, with Graphify re-extract only for changed files).

---

## Chunking (Claude Context)

- Designed for embedding-sized units with AST-aware boundaries (`SPLITTABLE_NODE_TYPES`), overlap, and LangChain fallback.
- Preserves semantic boundaries better than naive line splits for supported languages.
- Metadata can be prepended **without changing chunk boundaries** — inject string before embed only.

---

## Embeddings

Unchanged in this milestone. Only the text that will later be embedded changes (Phase 3).

---

## Overlap conclusion

Both systems use tree-sitter, but for different jobs:

1. **Graphify** = structure → `RepoIR` / graph metadata  
2. **Claude Context** = chunk → embed → retrieve  

Maintaining two *structural* pipelines would violate the experiment’s determinism and “no duplicate AST” constraint. Claude Context’s splitter is not a substitute for Graphify’s IR.

---

## Harness evidence

```text
pytest tests  →  5 passed
python -m parse_harness testdata/scubiee-news-flow --check-deterministic  → OK
```

Artifacts: `out/scubiee/bakeoff.json`, `out/scubiee/repo_ir.json`.
