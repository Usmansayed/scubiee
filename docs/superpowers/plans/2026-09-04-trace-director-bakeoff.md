# Trace Director Bakeoff Implementation Plan

> **For agentic workers:** implement A/B/C one-shot LLM directors; measure accuracy + latency on verify_hard.

**Goal:** BM25 + Graphify(+AST) propose numbered island → one warm `qwen3.5-0.8b-q4` call → TRACE PLAN → heatmap. Compare arms A/B/C for best hard-correct and &lt;5s/case.

## Results (10 hard cases, warm GPU) — 2026-09-04

| arm | hard | rec | prec | f1 | wall_s | &lt;5s |
|-----|------|-----|------|-----|--------|------|
| **polytrace** (baseline) | **5/10** | 0.87 | 0.88 | 0.82 | ~0 | 10 |
| director_A (cards, no body) | 0/10 | 0.29 | 0.61 | 0.39 | **5.2** | 1 |
| director_B (body slices) | 0/10 | 0.33 | 0.63 | 0.39 | 21.6 | 0 |
| director_C (judge+dense) | 0/10 | 0.26 | 0.62 | 0.36 | 17.8 | 0 |

**Verdict**
- **Fastest LLM arm:** A (~5s). Body packs (B/C) blow the 5s budget via prompt eval.
- **Best accuracy overall:** still **polytrace** — 0.8B one-shot KEEP/DROP does not beat structure yet.
- 0.8B often keeps too many / wrong set; clipping helps precision but kills must-recall.
- Next levers: use LLM only to **DROP hubs** on top of polytrace (not replace it); or train a tiny listwise head; or smaller packs (≤16 nodes) + forced short KEEP.

Raw: `docs/superpowers/plans/director-bakeoff-results.json`  
Run: `python -m trace_lab --director-bakeoff [--limit N]`
