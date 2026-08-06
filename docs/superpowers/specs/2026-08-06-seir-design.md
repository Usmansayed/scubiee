# SEIR — Embedding-Oriented Intermediate Representation (design)

**Status:** approved design; awaiting implementation plan  
**Date:** 2026-08-06  
**Corpus:** `testdata/frontend-mcp`  
**Gold:** `packages/conductor/hard_v2_gold.py` (`HARD_V2`)

## Goal

Discover whether a deterministic post-AST text representation embeds better for code retrieval than the text Context Engine already embeds today — under a hard density constraint (fewer tokens preferred when quality holds).

Tree-sitter / Graphify still produce the AST. SEIR starts **after** the AST exists. We do not invent a new parser.

## Constraints

- Use the **whole CE project setup** (parse helpers, CodeRank / accel embedder, FAISS, existing gold).
- Do **not** change production defaults, MCP, daemon, or shipping `CTX_COMPRESS` behavior.
- Plug-in style **B**: thin bench script + small transform module; may *import* pipeline code; must not replace the production path.
- No LLMs / summarization models — rule-based extraction only.
- Every extra token must earn its place (max semantic density, not max information).

## Non-goals (v1)

- Shipping SEIR as the default embed text
- Replacing `chunk_compress` or enrich
- Building a parallel indexer / HTTP daemon / MCP for this experiment
- Multi-language beyond what frontend-mcp already exercises (Python-first spans; other files skipped or pass-through as baseline source if needed)

## Architecture

```
frontend-mcp sources
        │
        ▼
 existing parse / AST (+ graph.json if present)
        │
        ▼
 shared function / class spans (same for every arm)
        │
        ├─► baseline     — CE embed text today (enriched / current compress path as used for index)
        ├─► ast_tree     — compact AST serialization
        ├─► rels         — relationship card (calls, called-by, reads, writes, returns)
        ├─► semantic     — rule labels (purpose, IO, boundary, deps)
        └─► importance   — high-score symbols/calls only
        │
        ▼
 CodeRank embed (accel) → temp FAISS collection per arm
        │
        ▼
 hard_v2 retrieval metrics + cost metrics → out/seir_ab_*.json
```

## Components

### 1. `packages/seir/` (new, experiment-only)

Pure, deterministic transformers. No I/O to production stores.

| Module | Responsibility |
|--------|----------------|
| `spans.py` | Derive function/class spans from AST / existing IR (align with CE chunk identity where practical: file + start/end line) |
| `ast_tree.py` | Experiment 1: compact indented AST (drop noise nodes; hard char cap) |
| `rels.py` | Experiment 2: relationship-oriented text from AST + optional Graphify edges |
| `semantic.py` | Experiment 3: rule-based purpose / inputs / output / boundary / deps (keyword + call heuristics; no LLM) |
| `importance.py` | Experiment 4: score extractables; keep high; drop logger/metrics/analytics-class noise |
| `baseline.py` | Load or reconstruct the text CE would embed for that span (reuse enrich/compress helpers via import; do not mutate indexer) |
| `caps.py` | Shared hard cap (default **512** chars) and token estimate helper |

Public API shape:

```python
def render(arm: str, span: SpanContext, *, max_chars: int = 512) -> str: ...
ARMS = ("baseline", "ast_tree", "rels", "semantic", "importance")
```

### 2. `scripts/seir_ab_bench.py` (new)

Orchestrates the A/B only:

1. Resolve repo = `testdata/frontend-mcp` (override via CLI).
2. Build shared span list once.
3. For each arm: render texts → embed with existing accel/CodeRank → write **temp** FAISS (under `out/seir_ab/<arm>/` or ephemeral under CTX-like local dir owned by the script).
4. Run `HARD_V2` queries; hit = gold `files_substr` match on retrieved paths.
5. Emit console table + `out/seir_ab_<timestamp>.json`.

CLI sketch: `python -u scripts/seir_ab_bench.py [--repo PATH] [--arms baseline,ast_tree,...] [--max-chars 512] [--top-k 10]`.

### 3. Reused (import only)

- Embedder / accel profile already used by CE  
- FAISS / vectordb helpers if usable without registering production projects  
- `HARD_V2` gold  
- Optional: existing `graph.json` / graph IR under the frontend-mcp project store for `rels` called-by edges  

If graph edges are missing, `rels` degrades to AST-local calls/reads/writes only (still valid; document in report).

## Representation formats (compact)

All arms truncated to `max_chars` with deterministic truncation (prefer keeping head identity lines).

**baseline** — whatever CE embeds for that span today (enriched + current default compress if that is how the corpus was indexed; document exact recipe in the JSON report `config` block).

**ast_tree** — readable tree, no full token dump:

```
FunctionDeclaration login
  params email password
  return
```

**rels**:

```
Function: login
Calls: bcrypt.compare generateJWT
CalledBy: LoginController
Reads: User.password
Writes: Session.token
Returns: JWT
```

**semantic** (rules only; empty fields omitted):

```
Function: login
Purpose: Authentication
Inputs: email password
Output: JWT
Boundary: Authentication
Deps: bcrypt SessionStore
```

**importance** — ranked lines only, e.g. `bcrypt.compare` / JWT helpers kept; `logger.*` / metrics dropped.

## Metrics

| Family | Metrics |
|--------|---------|
| Quality | Recall@1, Recall@5, Recall@10, MRR, nDCG@10 |
| Density | mean chars, mean est. tokens, total serialized bytes |
| Cost | embed ms / chunk, total embed wall time, collection size on disk |
| Latency | mean query latency |

Success (experiment): any SEIR arm beats `baseline` on a quality metric **or** matches quality within a small epsilon with clearly lower tokens/storage/embed time → candidate for a later integration discussion (not auto-merge into production).

## Testing

- Unit tests for each renderer: same AST fixture → stable string (golden or hash).  
- Bench smoke on a tiny subset (`--limit-spans N`) before full frontend-mcp run.  
- Full report committed or saved under `out/` (gitignored) + short markdown summary optional under `docs/` only if results warrant.

## Error handling

- Parse failures for a file: skip file, count in report `skipped`.  
- Embed/accel unavailable: fail fast with clear message (do not silently fall back to a different model).  
- Missing graph: continue with degraded `rels`.  

## Paper / idea notes (for later arms)

- CoCoAST: hierarchical AST split — denser than flat trees  
- Code vs Serialized AST: raw AST often ≠ win for sequence models → density + semantics matter  
- FAIR / MIREncoder: flow / call graphs as second modality → motivates `rels`  
- Possible v2 arms (out of scope now): SBT/NIT serialization, DFG-lite lines, path-context bags (code2vec-style) with strict caps  

## Implementation order

1. `packages/seir` renderers + span helper + unit fixtures  
2. `scripts/seir_ab_bench.py` smoke (`--limit-spans`)  
3. Full frontend-mcp + `HARD_V2` run  
4. Comparison report JSON (+ brief human summary if useful)  
