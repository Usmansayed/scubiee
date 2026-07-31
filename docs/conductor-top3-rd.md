# Conductor Top-3 R&D Track

Date: 2026-08-01

## Selection (consistency, not peak on one set)

| Rank | Arch | Role |
|------|------|------|
| 1 | `D_rerank` | Overall consistent — minrank pool + lexical/path rerank |
| 2 | `C_gear` | Semantic specialist — hybrid → expand → re-fuse |
| 3 | `A_minrank_expand` | Foundation — min-rank + path/symbol boost (D’s pool) |

**Excluded:** `F_f95` — overfit hard_v2.

## Eval surfaces (must all be reported)

| Surface | Purpose |
|---------|---------|
| `suite_bank` (S1–S5) | Style diversity (symbol/para/confusable/hop/terse) |
| `hard_v3` | Holdout targets vs hard_v2 |
| `diverse_bank` (D1–D5) | **LOCKED gate** — SEO/Figma/consistency/design/exec domains |
| `hard_v2` | Regression only |

**Consistency** = mean(suite macro R@5, holdout v3 R@5, diverse macro R@5).

## R&D rule

Accept an experiment only if:

1. consistency ≥ best control, and
2. diverse macro does not fall vs that control, and
3. holdout v3 does not fall vs that control.

Winning suites/v2 alone is a **reject**.

## Measure

```bash
.\.venv\Scripts\python -u conductor_top3_benchmark.py
```

## Experiments

| ID | Arch name | Idea | Status |
|----|-----------|------|--------|
| R&D#1 | `D2_pool_from_c` | Union C+A pools → D lexical rerank | NEUTRAL (= D) |
| R&D#2a | `M2` + MNZ-order RRF | A∪MNZ pool, D score, blend MNZ order | REJECT — consis 91.1% but diverse 92% (−2 vs D) |
| R&D#2b | `M2_mnz_dpath` | A∪MNZ pool, pure D path score | **ACCEPT NEUTRAL** — identical to D on all gates |
| R&D#2c | `M_mnz_rerank` | MNZ pool + D score + 0.5·MNZ mass | REJECT — consis 91.0% but diverse −4% |
| R&D#4a | `D_floor` | D + Graphify top-2 floor | Soft ACCEPT (80% R@5); consis REJECT (diverse −6%) |
| R&D#4b | `D_hippo` | Hybrid seeds → graph affinity → D | Soft REJECT (g_win 1/4); consis REJECT |
| R&D#4c | `X_soft` | Soft→hippo+floor else D+floor | Soft ACCEPT; consis REJECT (diverse −8%) |
| R&D#5a | `R_gated_floor` | SOFT-only lexically-gated ensure-floor (keep D top-3) | Soft ACCEPT (80%, MRR 0.62); consis REJECT (diverse −4%) |
| R&D#5b | `R_complex` | SOFT→hippo + gated floor | Soft ACCEPT; consis REJECT (diverse −4%, suites worse) |

**Takeaway:** A’s pool already covers files CombMNZ would add that D’s path score would promote. Letting MNZ into the *score/order* taxes diverse. Next: query-conditioned routing (C/MNZ on paraphrase; D on path-like).

### R&D#3 query router (`R_route_dc`)

| Variant | consis | suites | diverse | v3 | Gate |
|---------|--------|--------|---------|-----|------|
| v1 (C if p≤0.38) | 91.1% | 90.0% | 88% (−6) | **95.2%** | REJECT |
| v2 (C if p≤0.28, D-floor blends) | **91.8%** | **90.0%** | 90% (−4) | **95.2%** | REJECT |

Router is the strongest *consistency* candidate so far (+1.4 vs D) and sets a new holdout-v3 high (95.2%), but still taxes diverse. Promoting it requires either accepting a diverse trade or teaching the router that short technical NL in SEO/Figma domains stays on D.

### Channel math (suite+diverse, n=110)

Source: `out/conductor_channel_math.json`

| Channel | R@5 alone |
|---------|-----------|
| graph | **80.0%** |
| dense | 70.0% |
| hybrid | 61.8% |
| bm25 | 50.0% |

- **Oracle@5** (best single channel): graph 67 · dense 17 · bm25 15  
- **Exclusive@5** (only one of g/b/d hits): graph 11 · dense 5 · bm25 3 → need OR-style fusion  
- **Top-10 Jaccard**: g∩b 0.13 · g∩d 0.15 · b∩d 0.25 → channels are **complementary**, not redundant  
- Miss-all@5: 11/110 (10%) — fusion cannot invent these without better indexing

**Insight:** Graph is the strongest solo channel; BM25 is weakest alone but still has exclusive hits. Low overlap ⇒ CombMNZ/min-rank should help *recall*, but path/lexical rerank is what protects **diverse-domain** precision.

### Math fusion bake-off

| Arch | consistency | suites | diverse | v3 | Decision vs D |
|------|-------------|---------|---------|-----|----------------|
| **M_mnz_rerank** | **91.0%** | 90.0% | 90.0% | **92.9%** | REJECT (diverse −4% vs D’s 94%) |
| D_rerank (control) | 90.4% | 86.7% | **94.0%** | 90.5% | — |
| M_condorcet | 84.4% | 76.7% | 86.0% | 90.5% | REJECT |
| M_adapt_rrf | 82.5% | 75.0% | 82.0% | 90.5% | REJECT |
| M_combmnz | 82.0% | 75.0% | 78.0% | **92.9%** | REJECT |
| M_logisr | 80.9% | 73.3% | 86.0% | 83.3% | REJECT |

**Insights:**
1. Pure CombMNZ/LogISR/Condorcet/adapt-RRF **without path rerank** lose ~8–16pts diverse — rank fusion ≠ basename precision.
2. **CombMNZ alone** ties C on holdout v3 (92.9%) — agreement prior is real — but bleeds symbol/terse suites.
3. **M_mnz_rerank** is the strongest *overall* consistency candidate (+0.6 vs D) and lifts suites+v3; it fails only the strict “diverse must not fall” clause. Next R&D: keep MNZ pool but **blend D’s diverse-winning path boost** more aggressively (or accept a small diverse trade for higher suite/v3).
4. Cormack’s result (RRF > Condorcet) matches us: Condorcet mid-pack, not top.

### Next math-backed move

`M2_mnz_dpath` — CombMNZ candidate pool + **identical** D path/exact scoring (no MNZ score in rerank mix), optionally interpolate final list: `0.7·D_order ⊕ 0.3·MNZ_order` via RRF. Goal: keep diverse ≥ D while keeping suite gains.

## Soft R&D#4 (agent soft queries)

Locked gold: `packages/conductor/soft_bank.py` (OpenCode soft-30).  
Bake-off: `scripts/run_soft_arch_bakeoff.py` → `out/conductor_soft_bakeoff.json`.

| Arch | Soft R@5 | g_win | d_win | Soft gate | Consis | Diverse | Consis gate |
|------|----------|-------|-------|-----------|--------|---------|-------------|
| Graphify | 53.3% | 4/4 | 4/13 | REJECT | — | — | — |
| **D_rerank** | 73.3% | 1/4 | 13/13 | control | **90.4%** | **94.0%** | control |
| C_gear | 56.7% | 1/4 | 10/13 | REJECT | 83.5% | 76.0% | — |
| **D_floor** | **80.0%** | **3/4** | 13/13 | **ACCEPT** | 84.9% | 88.0% (−6) | **REJECT** |
| D_hippo | 73.3% | 1/4 | 13/13 | REJECT (g_win) | 87.8% | 92.0% (−2) | REJECT |
| **X_soft** | **80.0%** | **3/4** | 13/13 | **ACCEPT** | 83.7% | 86.0% (−8) | **REJECT** |

**Decision:** Do **not** replace production `D_rerank`. Soft gate proves Graphify-floor recovers agent losses; consistency/diverse gates prove naïve floor insertion taxes symbol/domain suites.

**Ship:** keep `D_rerank` default; expose experimental `d_floor` mode on API for soft-only trials. Next: floor that is **score-aware** (only promote G top-2 when G seed confidence high / channel disagreement low) so diverse does not fall.

## Soft R&D#5 (router-based)

Research-shaped stages: `query_state` (path_likeness) → D or HippoRAG dual-seed → **ensure-floor** only on SOFT when a Graphify hit is lexically grounded (path/substring/auth synonyms) and missing from D top-5; preserve D top-3.

| Arch | Soft R@5 | Soft MRR | g_win | Soft gate | Consis | Diverse | Decision |
|------|----------|----------|-------|-----------|--------|---------|----------|
| D_rerank | 73.3% | 0.600 | 1/4 | control | **90.4%** | **94.0%** | production |
| D_floor | 80.0% | 0.495 | 3/4 | ACCEPT | 84.9% | 88% | soft-only blunt tool |
| **R_gated_floor** | **80.0%** | **0.617** | **3/4** | **ACCEPT** | 85.8% | 90% (−4) | **best soft router; consis REJECT** |
| R_complex | 80.0% | 0.622 | 3/4 | ACCEPT | 85.2% | 90% (−4) | hippo adds little vs gated |

**Decision:** Still do not replace `D_rerank`. Prefer **`r_gated`** over `d_floor` for soft agent experiments (same soft R@5, much better MRR, smaller diverse tax). Next: reduce SEO-suite bleed (D1 70%) — likely false SOFT floors on short paraphrases — before any promote.

### OpenCode holdout (n=20, `/compare_rgated`) — overturns soft promotion

`out/opencode_rgated_ratings.md`: tie 8, miss_both 9, d_rerank 2, r_gated 1 → **`KEEP_D_ONLY`**. Lexical injection clobbered D’s correct #5 hits (`time`→timeout, `graph`→graph inits).

**Final architecture locked:** [`conductor-final-architecture.md`](conductor-final-architecture.md) — production = **`D_rerank` only**.
