# Graph + Hybrid Conductor (no LLM)

Date: 2026-08-01

## Problem

Weak embedders (e.g. local `nomic-embed-text`) miss paraphrased / jargon-heavy code queries. Graphify finds symbols and structure but returns NODE/EDGE text, not ranked code chunks. Claude Context hybrid (BM25 + dense → RRF) finds chunks but has no call/import graph.

## Decision

One **integrated scorer** — not three tools with a router. Every candidate chunk gets continuous **graph affinity**, **BM25**, and **dense** features; they are min-max normalized in a shared pool, linearly blended, lifted by multi-channel **agreement**, mixed with a geometric-mean “pull the strings” term, then **iterated** once with graph-neighbor expansion and rescore. No LLM; no lead-picking.

| Signal | Engine | Why |
|--------|--------|-----|
| Structure | Graphify lexical-IDF seed + BFS | Symbol/path precision, multi-hop neighbors |
| Lexical | Okapi BM25 over chunks | Exact identifiers (Claude Context sparse leg) |
| Semantic | Dense cosine (nomic) | Paraphrase recall |

## Research basis

- **Claude Context** already fuses dense + Milvus BM25 with RRF (`k=100`) inside `semanticSearch`; no graph awareness.
- **Graphify** is explicitly not a vector index: IDF/tier seed scoring → BFS/DFS → token-budgeted subgraph text.
- Production hybrid practice (Elastic/Milvus/OpenSearch, LightRAG hybrid seeding, HippoRAG-style expand): run lexical + dense (+ structure) in parallel, fuse by **rank** (scores are incomparable), then walk the graph from seeds.
- For **code**, lexical and structure outweigh weak dense: default weights `bm25=1.0`, `graph=1.0`, `dense=0.5`, RRF `k=60`.

## Algorithm (Conductor v3 — min-rank fusion)

1. Graphify affinity → file rank list.
2. BM25+dense RRF (Claude Context–style) → file rank list.
3. **Min-rank fusion:** each file keeps `min(rank_graph, rank_hybrid)`; files seen by both get a small rank bonus.
4. Neighbor files of seeds can enter at a soft rank.
5. Inside each file, pick chunk by combined graph+BM25+dense mass.

One shared file ranking — the three signals pull the same strings.

## What we are not building

- GraphRAG community-summary global search
- LLM tool-calling conductor / cross-encoder reranker
- Dual AST parsers (single Graphify parse → RepoIR → chunks)
- “Call Graphify **or** Claude Context” routing as the product behavior

## A/B arms

`graphify` | `hybrid` (BM25+dense RRF) | `conductor` (v3 integrated joint) on the same hard-gold file substrings.
