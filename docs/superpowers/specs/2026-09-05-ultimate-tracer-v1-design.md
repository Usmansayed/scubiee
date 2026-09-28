# Design: Ultimate Tracer v1

**Date:** 2026-09-05  
**Status:** approved — implementing  
**Source:** `SCUBIEE_SEMANTIC_TRACER_RESEARCH.md` §34 + prior polytrace winner

## Goal
Non-LLM semantic tracer: query + seed → smallest useful behavioral heatmap.

## v1 (on top of polytrace channels)
1. Query-conditioned edge weights (`flow|config|refs|site|entry`)
2. Code-IDF / generic hub penalty (degree + logger/helpers)
3. Path reinforcement (multi-path score boost)
4. Best-first expand + light Personalized PageRank rescoring on discovered subgraph
5. One-shot semantic teleport (BM25 → admit only if structural edge to reachable set)
6. Information-gain / frontier stopping (not only hop cap)

## Out of v1
Joern/CPG, GNN, LightGBM, full CFG/PDG rewrite.

## Ship rule
Bakeoff vs `polytrace` on `verify_prod` (2026-09-05):
- polytrace F1 **0.784** (rec 0.917 / prec 0.734)
- ultimate_trace F1 **~0.73** (higher precision, lower recall)

**Default remains `polytrace`.** Opt in with `CTX_TRACE_ENGINE=ultimate`. Continue tuning (PPR off by default; teleport + path reinforce + edge priors on).
