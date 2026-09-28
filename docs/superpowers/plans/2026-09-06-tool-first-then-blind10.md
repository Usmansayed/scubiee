# Tool-first, then blind-10 pack compare

**Rule:** No multi-arm “winner” claims until each underlying tool is green in isolation.

## Phase 0 — Internal tool gates (must be 100% green)

Run in order; **stop on first failure**.

| # | Tool | Proof command | Pass criteria |
|---|------|---------------|---------------|
| T1 | ORT + DML | `python -c "import onnxruntime as ort; assert 'DmlExecutionProvider' in ort.get_available_providers()"` | DML present |
| T2 | Product Embedder | `python scripts/venture_preflight.py` (or pytest below) | `embed_device=dml`, backend fastembed, dim 768 |
| T3 | Product FAISS search | same preflight | ≥1 hit on **product repo**; error=null |
| T4 | Publication usable | `index_is_usable(store)` | True (checksum valid) |
| T5 | EmbedField real | `EmbedField(..., require_real=True)` | `backend` starts with `real:` |
| T6 | Propose→verify | unit tests in `tests/test_venture_stack.py` | admits only hop-verified nodes; rejects sinks |
| T7 | Venture arm smoke | each `venture_*` returns heatmap with seed hot | no exception |

**pytest entry:**

```bash
$env:PYTHONPATH="packages"
.\.venv\Scripts\python.exe -m pytest tests/test_venture_stack.py -q --tb=short
.\.venv\Scripts\python.exe scripts/venture_preflight.py
```

Only when **both** exit 0, proceed to Phase 1.

## Phase 1 — Blind production-like pack compare (10 hard)

**Do not look at gold until Phase 2.**

1. Author **10 enrich prompts** (new IDs `b01`–`b10`) aimed at hard locate/pack tasks. Save:
   - `docs/superpowers/plans/2026-09-06-blind10-pack-queries.json`
2. For each prompt:
   - Run **map** (CLI/`map_context`) → take top cards / suggested seed + **pasteable chunks** (file+symbol+body excerpt).
   - Build pack input = enrich prompt + seed chunks (production-like agent paste).
   - Run **pack** for each arm under test (default set: `composite_v1`, best venture arm if T6–T7 green, optionally fuse).
   - **Freeze** raw outputs only (no scoring):
     - `docs/superpowers/plans/blind10_pack_runs/{id}_map.json`
     - `docs/superpowers/plans/blind10_pack_runs/{id}_pack_{arm}.json`
3. Write frozen summary:
   - `docs/superpowers/plans/2026-09-06-blind10-pack-results.json`

Harness: `scripts/blind10_pack_phase1.py` (map→chunks→pack→store).

## Phase 2 — Verify all at once

1. Independently author GT for `b01`–`b10` (must files/symbols) **after** Phase 1 freeze.
2. Score all arms against GT in one pass:
   - `scripts/blind10_pack_phase2.py`
3. Report: must-file / must-symbol / thin packs / seed OK — no mid-run peeking.

## Explicit bans

- No bakeoff “winner” if preflight failed or FAISS returned 0 hits.
- No hash embeds in production-like arms (`require_real_embeds=True`).
- No silently swallowing search/embed errors in venture helpers.
- No crowning arms that only demote noise when the claim is “vector proposal.”

## Status

- [x] Phase 0 suite green — `tests/test_venture_stack.py` **7 passed**; `venture_preflight.py` **PREFLIGHT OK** (product meta.root=context-engine, **5791** chunks, FAISS hits). Product index rebuilt after fixture contamination; do **not** `search_repo(fixtures/trace-lab)` under the product project_id.
- [ ] Phase 1 frozen for b01–b10 — harness ready: `scripts/blind10_pack_phase1.py` + queries `2026-09-06-blind10-pack-queries.json` (production `composite_v1` pack only until venture arms are wired into pack CLI)
- [ ] Phase 2 scored — `scripts/blind10_pack_phase2.py` waits on GT file authored **after** freeze
