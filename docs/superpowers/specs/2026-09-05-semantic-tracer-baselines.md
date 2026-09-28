# Semantic tracer baselines (Phase 1 — frozen)

Immutable bakeoff baselines — do not “improve” by silent rewrite:

| Arm | Role |
|-----|------|
| `bm25_body` | Lexical-only heatmap |
| `ast_propagate` | Undirected/weighted AST walk |
| `polytrace` | Production default: LSP-sim + AST + Graphify + faction + best-first |

New layered arms (`callgraph_jedi`, `dfg_slice`, `pdg_prio`, `hybrid_teleport`, `rank_default`, `rank_strict`) are additive. Default MCP engine remains `polytrace` until ship gate.
