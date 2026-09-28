# Semantic combo bakeoff — `verify_hard.json`

Cases: 50 · Variants: 55 · Backend: `real:fastembed` · 19.16s

## Baseline (`composite_v1`)

- Acc 0.42 · F1 0.7776 · Must-rec 0.8044 · Prec 0.8499

## Top 15 by must-rec → F1 → acc

| Arm | Acc | F1 | Must | Prec | Keep? |
|-----|-----|----|------|------|-------|
| `hybrid_teleport` | 0.06 | 0.3176 | 0.8757 | 0.2281 | no |
| `embed_teleport_add_m25k12` | 0.34 | 0.7069 | 0.8684 | 0.6361 | no |
| `embed_teleport_m25k12` | 0.34 | 0.7069 | 0.8684 | 0.6361 | no |
| `stack_bm25_embed_add` | 0.38 | 0.7222 | 0.8617 | 0.6599 | no |
| `bm25_teleport` | 0.42 | 0.7431 | 0.8567 | 0.7035 | no |
| `embed_teleport_add_m30k20` | 0.4 | 0.7463 | 0.8444 | 0.7237 | no |
| `embed_teleport_m30k20` | 0.4 | 0.7463 | 0.8444 | 0.7237 | no |
| `embed_teleport_add_m35k12` | 0.42 | 0.7573 | 0.8394 | 0.7472 | no |
| `embed_teleport_m35k12` | 0.42 | 0.7573 | 0.8394 | 0.7472 | no |
| `poly_embed` | 0.26 | 0.7915 | 0.8153 | 0.8517 | YES |
| `embed_teleport_add_m45k8` | 0.42 | 0.7722 | 0.8111 | 0.8179 | no |
| `embed_teleport_m45k8` | 0.42 | 0.7722 | 0.8111 | 0.8179 | no |
| `add_gate_q30s70` | 0.42 | 0.7776 | 0.8044 | 0.8499 | no |
| `add_gate_q50s50` | 0.42 | 0.7776 | 0.8044 | 0.8499 | no |
| `add_gate_q60s40` | 0.42 | 0.7776 | 0.8044 | 0.8499 | no |

**Best by ranking:** `hybrid_teleport`

**Keep-gate winners:** ['poly_embed']

## Verdict

Formal keep-gate listed `poly_embed` (must↑ + F1↑ + prec flat), but **hard accuracy fell 0.42 → 0.26** — not a production win.

Raw must-rec leaders (`hybrid_teleport`, aggressive `embed_teleport_*`) **buy recall by dumping precision** (prec 0.23–0.64) and fail the keep gate.

### What we actually ran (55 variants × 50 hard cases)

| Kind | Example | Must | F1 | Acc | Prec |
|------|---------|------|-----|-----|------|
| Structural baseline | `composite_v1` | 0.804 | 0.778 | **0.42** | **0.850** |
| Pure vector search | `vector_only` | **0.281** | 0.399 | **0.00** | 0.907 |
| Embed teleport (loose) | `embed_teleport_m25k12` | **0.868** | 0.707 | 0.34 | 0.636 |
| BM25 teleport | `bm25_teleport` | 0.857 | 0.743 | 0.42 | 0.704 |
| Stack BM25+embed+add | `stack_bm25_embed_add` | 0.862 | 0.722 | 0.38 | 0.660 |
| System hybrid_teleport | `hybrid_teleport` | **0.876** | 0.318 | 0.06 | 0.228 |
| Poly embed rerank | `poly_embed` | 0.815 | **0.792** | 0.26 | 0.852 |
| Rank-only α/τ/weight sweeps | `add_*` / `gate_*` | 0.804 | 0.778 | 0.42 | 0.850 |

**Bottom line:** Pure semantic search does **not** win on hard checks. Teleport raises must-rec but fails balanced quality. Keep `composite_v1` as default; next research = *stricter* verified teleport (higher min_sem + must_not-aware admission), not dumping vector top-k.
