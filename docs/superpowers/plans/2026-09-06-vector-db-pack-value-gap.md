# Research problem: Vector DB does not add product value to pack/locate

**Date:** 2026-09-06  
**Status:** open — research brief (not a ship decision)  
**Owner context:** Scubiee / context-engine locate ladder (`map` → `pack` → `expand`)  
**Production pack default today:** `composite_v1` (structural graph tracer)

---

## 1. One-sentence problem

**We already pay for a production CodeRank + FAISS vector index (thousands of chunks, MCP map/search), but our pack/trace path cannot use that vector space to recover missing must-symbols or beat a pure structural tracer on recall — embeds mostly demote noise inside an island the graph already proposed.**

If structure misses a hop, semantics usually miss it too. If structure already sits on the right file, semantics cannot show recall wins. So “composite + semantic” looks equal to “composite alone” on the metrics that matter for shipping.

---

## 2. Why this matters for the product

| Product surface | What vectors do today | What agents need from pack |
|-----------------|----------------------|----------------------------|
| MCP / CLI **map** / search | Real FAISS neighbors over **enriched chunks** | Soft entry → suggested seed |
| MCP / CLI **pack** | Almost entirely **AST/call/DFG graph** (`composite_v1`) | Hot bodies + chain for editing |
| Research arms (`semantic_tracer_fuse`, `hyb_*`, `poly_embed`) | Second embed field over **symbol AST nodes**, not the product FAISS | Same pack job, hoped-for better island |

**Gap:** the expensive, working vector DB is upstream of locate (map/search). The edit-critical step (pack) does not *propose* from that DB. Research “semantic pack” still does not invent edges from vectors; it filters a structural island.

**User-visible symptom:** adding “semantic search power” to pack does not reliably find the second file / sibling symbol the agent still needs (`diff_chunk_records`, `compress_chunk`, `cmd_certify`, …). It only sometimes makes the pack quieter.

---

## 3. Two vector spaces (architecture mismatch)

We effectively have **two embedding worlds**:

### A. Product index (works, ~minutes to sync)

- Store: `~/.scubiee/vectordb/collections/…` + project meta  
- Unit: **enriched / compressed chunks** (CodeRankEmbed, dim 768, FAISS + turboquant)  
- Observed healthy on this repo: **~5742 chunks**, `embed_model=nomic-ai/CodeRankEmbed`, index usable, map/pack CLI OK  
- Used by: engine search, soft **map**, incremental sync  

### B. Trace-lab `EmbedField` (research pack arms)

- Store: repo `.embed_cache/coderank.jsonl`  
- Unit: **symbol-level AST nodes** — doc ≈ `file\nsymbol\nbody[:1200]`  
- Built by `compile_bundle(..., with_embed_power=True)` → `EmbedField` → affinities for fuse/hybrid/poly_embed  
- **Not** wired to product FAISS collections  

So even when research arms use “real CodeRank,” they are **not** “query the same vector DB the MCP uses.” They re-embed a different corpus (symbols) into a side cache.

### Historical footgun (fixed 2026-09-06, still instructive)

- Venv had CPU `onnxruntime` shadowing `onnxruntime-directml` → DML planned, CPU executed, ~1 chunk/s  
- `EmbedField` hardcoded `batch_size=8` (now uses accel default)  
- A blind multipack was wrongly scored on **hash** embeds after aborting a slow run — that result is **invalid** for semantic claims  

After fix: DML batch=16, ~12+ chunk/s, full symbol field ~5 min (3770 new + 1280 cached). Product index was already fine.

---

## 4. How “semantic pack” actually uses embeddings

Documented design (see `packages/trace_lab/embed_filter.py`, `semantic_tracer_fuse.py`, `poly_embed.py`):

```text
Structure proposes the island (calls / DFG / membership / polytrace)
    → embeddings keep / drop / demote / rescore INSIDE that island
    → does NOT invent edges from the vector DB
```

`semantic_tracer_fuse` default: **`with_teleport=False`**.  
Strict embed teleport exists as ablation and historically **hurt F1/precision** on fixture boards (`semantic_tracer_fuse_teleport`).

**Implication:** vectors are a **precision / noise** tool, not a **recall / proposal** tool. On boards where the seed is already correct, must-recall is capped by the graph; embeds cannot beat composite on must-hit rate.

---

## 5. Experiments we ran (chronological / thematic)

Artifacts live under `docs/superpowers/plans/` unless noted. Scripts under `scripts/`.

### 5.1 Fixture / OOD bakeoffs (research arms vs `composite_v1`)

| Experiment | Artifact / script | What we tested | Headline |
|------------|-------------------|----------------|----------|
| Composite × semantic phase 0 | `2026-09-06-composite-semantic-phase0-bakeoff.md` | Early combo grid | Structure still carries membership |
| Semantic tracer v1 hard/prod | `2026-09-06-semantic-tracer-v1-*.md` | Comparator in best-first | Some must@10 / F1 movement; not a default flip |
| Semantic tracer fuse hard/prod | `2026-09-06-semantic-tracer-fuse-*.md` | Fuse recipe + teleport ablation | Fuse competitive; **teleport off** for default |
| Semantic OOD v2 | `2026-09-06-semantic-ood-v2-*.md` | OOD boards | `poly_embed` sometimes strong; not universal |
| Hybrid combo cross-board | `2026-09-06-hybrid-combo-crossboard.md` | `hyb_fuse_demote_noise_plus` etc. | Noise demote helps precision on some boards |
| Pre-switch consistency v5–v7 | `2026-09-06-pre-switch-consistency-v5-v7.md` | Don’t flip MCP until consistent | Composite remains production |
| Rich context v8 | `2026-09-06-rich-context-v8.md` | Richer queries | Mixed |
| Distributed v9 | `2026-09-06-distributed-v9.md` | Distributed cases | Mixed |
| Realistic agent input v10 | `2026-09-06-realistic-v10.md` | Paragraph + pasted seed chunks + multi-seed merge | `poly_embed` best **acc** on that board; fuse **tied** composite on must for several failures; embeds help when island incomplete **only if** filter path still keeps musts |
| R&D synthesis Cycles 1–3 | `2026-09-06-semantic-tracer-rnd-synthesis.md` | Mechanism keep/drop table | **Pure vector_only = Acc 0 on hard**; loose hybrid_teleport must↑ / prec collapse; strict teleport not default |

**Synthesis takeaway (already written):** graph membership is required; pure vector retrieval is not a pack replacement; teleport is dangerous; fuse is “structure + soft semantic tint,” not “FAISS pack.”

### 5.2 Blind protocol — composite-only pack (t01–t20)

| Item | Path |
|------|------|
| Queries | `2026-09-06-blind-map-pack-20-queries.json` |
| Runner | `scripts/blind_map_pack_20.py` |
| Results | `2026-09-06-blind-map-pack-20-results.md` |
| GT + phase 2 | `2026-09-06-blind-map-pack-20-ground-truth.json`, `…-phase2.md` |

**Protocol:** author enrich queries without looking up gold → `scubiee map` → `scubiee pack` (production = **composite_v1** only) → then independent GT.

**Phase-2 headline (composite lean only):**

| Metric | Value |
|--------|-------|
| Seed in must-files | 80% |
| Map must-file recall | ~78% |
| Pack must-file recall | ~55% |
| Pack must-symbol recall | ~33% |
| Thin packs (n_pack &lt; 2) | 13/20 |

**Product signal:** even without comparing arms, **pack under-delivers symbols** relative to map. Vectors are not fixing that in production pack today.

### 5.3 Blind multipack — 4 arms, NEW queries (u01–u20)

| Item | Path |
|------|------|
| Queries (different from t01–t20) | `2026-09-06-blind-multipack-20-queries.json` |
| Maps | `2026-09-06-blind-multipack-20-maps.json` |
| Pack runner | `scripts/blind_multipack_pack_only.py` |
| GT + phase 2 | `2026-09-06-blind-multipack-20-ground-truth.json`, `…-phase2.md` |
| Arms | `composite_v1`, `semantic_tracer_fuse`, `hyb_fuse_demote_noise_plus`, `poly_embed` |

**Invalid run:** hash-embed multipack (aborted CodeRank) — do not cite for semantic value.

**Valid run:** real CodeRank DML, `require_real_embeds=True`, ~5050 nodes, embed ~5.2 min.

**Phase-2 (must coverage of top15 ∪ hot):**

| Arm | Pack must-file | Pack must-sym | Mean hot | Thin ≤3 |
|-----|----------------|---------------|----------|---------|
| `semantic_tracer_fuse` | **0.850** | **0.575** | **43.3** | 5/20 |
| `composite_v1` | **0.850** | **0.575** | 66.0 | 5/20 |
| `hyb_fuse_demote_noise_plus` | **0.850** | **0.575** | 83.7 | 5/20 |
| `poly_embed` | 0.775 | **0.575** | 1.8 | 17/20 |

Shared map: must-file **0.95**, seed in must-files **1.00**.

**Per-case pattern:** fuse and composite share **identical missing must-symbols** on nearly every task (e.g. both miss `chunk_merkle.diff_chunk_records`, both miss `compress_chunk` / `resolve_compress_mode`, both miss `cmd_certify`, …). Fuse only reduces mean heat.

**Interpretation:** on a **seed-perfect** blind board, semantic arms add **no recall value**; they add **noise shaping**. `poly_embed` over-filters (thin) without recovering the same misses.

### 5.4 Tooling / embed health checks (same day)

| Check | Result |
|-------|--------|
| `scubiee status` | Enrolled, 5742 chunks, index clean/usable |
| Accel after DirectML fix | `DmlExecutionProvider` + batch 16 |
| CLI map + pack smoke | OK |
| `scripts/semantic_stack_smoke.py` | SMOKE PASS (real DML) |
| Focused pytest (embed/semantic/locate/lean) | 87 passed after lean `expand` text fix |

**Side bug found:** lean MCP treated session/nav `expand` (handle → body) like locate `expand_context` and stripped `text` — fixed in `mcp_response_lean.py`. Orthogonal to vector-value problem but shows pack/nav response shaping can hide bodies.

---

## 6. Concrete failure modes (vector “adds no value”)

1. **Proposal gap** — Missing must is off the structural frontier → no arm with teleport-off can hit it; miss lists match composite.  
2. **Index gap** — Product FAISS neighbors never become pack seeds/nodes; map cards don’t automatically inject into pack membership.  
3. **Corpus gap** — Symbol `EmbedField` ≠ chunk FAISS; affinity scores don’t mean “same as MCP search.”  
4. **Metric gap** — Bakeoffs that score must-hit on seed-easy boards reward structure; embed-only precision wins look like “ties.”  
5. **Teleport trap** — When we *did* allow embed proposal (strict/loose teleport), fixture evidence was precision collapse or F1 drop — so we disabled the only path that could raise recall via vectors.  
6. **Thin pack trap** — Aggressive keep/drop (`poly_embed`) looks “semantic” but returns almost no bodies; agents still fail the task.

---

## 7. What “using the vector DB properly” would mean (research targets)

These are **hypotheses to test**, not decided designs:

1. **Chunk→symbol bridge** — From FAISS top-k chunks, resolve to AST node ids and **union** into pack membership (proposal), then rank with composite/fuse.  
2. **Map→pack handoff** — Treat soft-map cards (already vector-backed) as **multi-seed** or forced membership, not just one `suggested_seed`.  
3. **Asymmetric proposal, structural verify** — Vectors propose; graph must confirm path/edge (avoid teleport precision collapse).  
4. **Same embed space** — Pack affinities read **product** vectors / same doc template as indexer, not a second symbol cache.  
5. **Hard boards for recall** — Evaluate only cases where composite **misses** a must-symbol; measure Δ must-recall of vector proposal. Seed-perfect boards will always look like ties.  
6. **Agent metric** — Not only must-hit: edit success / expand hops / tokens to first correct body.

---

## 8. Suggested research questions

1. On the u01–u20 miss set, can FAISS neighbors from the **product** collection surface the missing symbols within top-20 chunks?  
2. If yes, what join (chunk → file → symbol) recovers them without heating logger/analytics?  
3. Does multi-seed from map top-5 beat single seed more than any embed filter arm?  
4. Is there a teleport policy that recovers musts with precision ≥ composite on a held-out OOD board?  
5. Should pack stay structural-only while vectors stay map-only — and we invest in map→pack seed quality instead?

---

## 9. Current stance (for researchers)

- **Do not** claim “semantic pack = composite + vector search power” with current code — it is **composite + affinity filter**.  
- **Do** treat product FAISS as proven for **map/search**, unproven for **pack membership**.  
- **Ship default remains `composite_v1`** until a vector **proposal** path beats composite on **must-recall** without precision collapse on a blind, seed-hard board.  
- Blind multipack with real DML is the clearest live-repo evidence of the recall tie; fixture bakeoffs show occasional precision/acc wins that did not transfer to a production flip.

---

## 10. Key file pointers

| Role | Path |
|------|------|
| Product embed / index | `packages/pipeline/embedder.py`, `packages/pipeline/indexer.py` |
| Pack engine switch | `packages/pipeline/context_trace.py` (`CTX_TRACE_ENGINE`) |
| Composite | `packages/trace_lab/composite_v1.py` |
| Fuse | `packages/trace_lab/semantic_tracer_fuse.py` |
| Embed filter / poly_embed | `packages/trace_lab/embed_filter.py`, `poly_embed.py` |
| Trace-lab embed field | `packages/trace_lab/embed_field.py` |
| Teleport | `packages/trace_lab/semantic_teleport.py` |
| Blind multipack | `scripts/blind_multipack_*.py` |
| This problem statement | `docs/superpowers/plans/2026-09-06-vector-db-pack-value-gap.md` |

---

## 11. Appendix — example identical misses (real-embed multipack)

Illustrative: composite and fuse fail the **same** symbols; fuse only lowers heat.

| Case | Missing must-symbol(s) | composite hot | fuse hot |
|------|------------------------|---------------|----------|
| u01 | `chunk_merkle.diff_chunk_records` | 330 | 218 |
| u02 | `compress_chunk`, `resolve_compress_mode` | 12 | 12 |
| u05 | `maybe_demote_idle`, `apply_tier` | 1 | 1 |
| u06 | `cmd_certify` | 334 | 186 |
| u15 | `cmd_expand` | 124 | 98 |

That table is the empirical shape of the problem: **vectors are not filling the holes structure leaves.**
