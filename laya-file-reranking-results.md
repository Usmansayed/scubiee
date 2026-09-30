# Does Laya-Code Improve Scubiee File-Level Retrieval? — Experiment Results

Rigorous evaluation of **`tindang/laya-code`** as a *second-stage file reranker* on top of
Scubiee's production `map` retrieval. Question: **does adding Laya as a reranker locate the
correct files better than Scubiee alone?**

Scubiee's production retrieval was **not modified**. The baseline is captured from the live
`map` MCP tool; all Laya reranking / fusion / metrics run in a separate offline harness.

---

## TL;DR recommendation

**Marginal. Adopt only as score *fusion*, never as a Laya-only reranker, and only after fixing
the real bottleneck (recall), which reranking cannot.**

- Scubiee baseline is already strong: **MRR 0.882**, Recall@5 0.70.
- Best reranked config lifts MRR to **~0.90–0.92** (fusion ≈ 0.90, Laya-on-full-file ≈ 0.917) — a
  **+0.02 to +0.04** gain.
- **Fusion helped 3 tasks, hurt 1, left 14 unchanged.** Laya-*alone* helped 3 and **hurt 3** (a wash).
- The dominant limiter is **retrieval recall, not ranking**: Scubiee only put **73%** of relevant
  files into the candidate pool, so Recall@10 is capped at ~0.73 for *every* config. A reranker
  cannot recover a file that was never retrieved.

**Verdict:** the file-level ranking gain is real but small and comes with a per-file model-call
cost. It does **not**, on its own, justify adding Laya as a mandatory second stage. It is worth a
**guarded fusion** experiment for the specific failure mode it fixes (distractor files out-ranking
real ones), *after* widening first-stage recall.

---

## Methodology

**Benchmark:** 18 real multi-file Scubiee commits (2–5 changed source files each), task text =
commit subject + first body line (release-version prefixes stripped). Relevant files = the
source files the commit changed (verified present in the tree). Built by
`build_tasks.py` → `tasks.json`.

**Stage 1 — baseline (unmodified Scubiee):** for each task, the production `map` tool (k=25, dense
`D_channel_best`) returns ranked chunk cards; we aggregate to **file level** (best-ranked card per
file), preserving Scubiee's score and order. Captured in `baseline_maps.json`.

**Stage 2 — Laya rerank (offline harness `run_rerank_eval.py`):** every candidate file is scored
**independently** with Laya (`P(relevant | task, file-state)`), concurrently (4 workers). Three
**state variants** per file:
- `chunk` — the exact Scubiee card span (what Scubiee retrieved),
- `window` — ~120 lines centered on the card,
- `file` — the whole file, truncated to ~6000 chars (the model truncates to 512 tokens internally).

**Configs:** A baseline (Scubiee order) · B Laya rerank (per variant) · C fusion
`w·norm(scubiee)+(1−w)·laya`, w∈{0.3,0.5,0.7} · D top-K filter (fusion w=0.5 → top-5).

**Metrics** (macro-avg over 18 tasks): Recall@1/5/10, Precision@5/10, MRR, first-relevant rank,
whether Laya moved a relevant file up/down, latency, #calls, approx input tokens.

**Runtime:** Laya on CPU (stable over ~250 sequential calls; the 4 GB AMD GPU OOMs on long runs).
Scores are device-independent.

---

## Aggregate results (18 tasks)

| Config | Recall@1 | Recall@5 | Recall@10 | Precision@5 | MRR |
|--------|---------:|---------:|----------:|------------:|----:|
| **A — Scubiee baseline** | 0.277 | 0.697 | 0.730 | 0.456 | **0.882** |
| B — Laya rerank (chunk) | 0.263 | 0.730 | 0.730 | 0.478 | 0.889 |
| B — Laya rerank (window) | 0.210 | 0.716 | 0.730 | 0.467 | 0.833 |
| **B — Laya rerank (file)** | 0.273 | 0.730 | 0.730 | 0.478 | **0.917** |
| C — fusion w=0.3 | 0.272 | 0.711 | 0.730 | 0.467 | 0.907 |
| C — fusion w=0.5 | 0.272 | 0.711 | 0.730 | 0.467 | 0.903 |
| C — fusion w=0.7 | 0.272 | 0.711 | 0.730 | 0.467 | 0.900 |
| D — fusion→top5 | 0.272 | 0.711 | 0.711 | 0.467 | 0.903 |

**Reading it right (per the brief — judge ranking, not absolute probabilities):**
- Every config shares **Recall@10 ≈ 0.73** — the retrieval ceiling (see below). Reranking only
  moves files *within* the retrieved set.
- MRR is where reranking can help. Best: **Laya on the full-file state (0.917)** and **fusion
  (0.90–0.91)**, both above baseline 0.882.
- `window` state is **worse than baseline** (0.833) — a partial window misleads Laya.

## The real bottleneck: retrieval recall (the ceiling)

**Scubiee retrieved, on average, only 73% of each task's relevant files into the candidate pool;
12 of 18 tasks were missing at least one relevant file.** Examples:
- `b4c4baf` ("clean output overhaul", 4 relevant files) — only **1/4** retrieved.
- `43eca40` ("status flags follow AST cache", 5 files) — only **2/5** (`context_trace.py`,
  `mcp_locate.py`, `runtime_controller.py` never surfaced).
- `76656f9` (leaner MCP JSON, 5 files) — **2/5**.

No reranker — Laya or otherwise — can fix these; the files aren't in the pool. **This is the
single biggest lever on file-level retrieval quality, and it is upstream of any reranker.**

## Latency / cost

- Laya file scoring: **avg ~1.0 s, median ~0.9 s, p95 ~1.7 s per file on CPU** (~120 ms/file on the
  AMD GPU). One call per candidate file per task.
- Total for the 18-task sweep (3 state variants): ~250 Laya calls.
- Approx input: each file-state is capped at ~6000 chars ≈ **~1.5k input tokens per call**. In a
  real pipeline (one variant, ~5 candidate files) that's ~5 model calls and ~7.5k tokens of *Laya*
  input per query — but note **Laya emits 0 output tokens** (it's a classifier), so it does not add
  to the *agent's* LLM token bill; it adds compute latency and its own inference cost.

---

## Where Laya clearly helped

1. **`757faaf` — "pin the model cache before fastembed can resolve it"** (all 4 relevant retrieved).
   Baseline MRR **0.33**: Scubiee ranked distractors `graphify/cache.py` and `coreml_mac.py`
   above the real files. Laya-file and fusion → **1.00**. The real fix files scored higher on
   task relevance than the lexically-similar cache distractors.
2. **`bc9c63b` — "project MCP pins for Cursor and other hosts"** (2/3 retrieved). Baseline **0.20**
   (Scubiee put `wipe.py` #1). Laya-file → **1.00** by surfacing the actual config writer.
3. **`9bae27b` — "workspace-local MCP config for Kiro/Copilot/Cline/Roo"**. Baseline **0.33** →
   Laya-file **1.00** (fusion 0.50). Same pattern: Scubiee's top hit was `wipe.py`; Laya preferred
   the connect/rules writers.

Common thread: Laya helps most exactly where the brief predicted — **several files look
superficially relevant and Scubiee's lexical/dense score ranks a distractor first.** Laya's
task-conditioned relevance breaks that tie correctly.

## Where Laya hurt

1. **`23e6ebe` — "pin model cache out of OS temp dir"** (fusion 1.00→**0.50**). Scubiee gave the
   capability-stub `model_cache.py` a huge score (79.7); fusion's normalization over-weighted it
   and pushed the genuinely-edited `coreml_mac.py` off the top. **Fusion is sensitive to
   Scubiee's occasional very-large capability scores.**
2. **`43eca40`, `76656f9`, `f2a8fbf`** — Laya-*alone* on the full file knocked a correct baseline
   #1 down to #2 (e.g. `f2a8fbf`: baseline had `__main__.py` #1, Laya-file promoted `cli_ui.py`
   above it). **Fusion protected against all three** (stayed at 1.00), which is the core argument
   for fusion over Laya-alone.

## State variant finding (what to feed Laya)

Feeding Laya the **whole file** (`file`, MRR 0.917) beats the **retrieved chunk** (`chunk`, 0.889)
and clearly beats a **120-line window** (`window`, 0.833, *below baseline*). The window variant
strips the surrounding context Laya needs and misleads it. If Laya is adopted, pass the full file
(truncated), not the isolated Scubiee chunk. (Files are truncated to the model's 512-token window;
we pass the first ~6000 chars — documented in `run_rerank_eval.py::state_variants`.)

## Movement summary

Laya-chunk moved a relevant file **up in 12 tasks and down in 11** — i.e. left to itself it is
nearly a coin flip on any individual task, even though the *average* MRR nudges up. This variance
is the reason to prefer **fusion** (which anchors on Scubiee's already-good order and only
overrides when Laya is confident): fusion helped 3, hurt 1.

---

## Does Laya justify adding it as a second-stage reranker in Scubiee?

**Not as currently measured — not yet.** Reasoning:

1. **Small ceiling on the gain.** Baseline MRR is already 0.88. Best reranking reaches ~0.90–0.92:
   a real but modest +0.02–0.04, and Recall@10 does **not** move at all (0.73 → 0.73).
2. **The binding constraint is recall, not ranking.** 27% of relevant files never reach the pool.
   Effort spent widening first-stage retrieval (higher k, better multi-file recall, graph
   expansion of candidates) would raise the ceiling far more than reranking the 73% that already
   arrive.
3. **Laya-alone is unsafe** (helped 3 / hurt 3). Only **fusion** is net-positive-and-low-risk, and
   even fusion is fooled by Scubiee's occasional huge capability scores (`23e6ebe`) — it needs
   score-normalization hardening before it could ship.
4. **Cost is non-trivial:** one Laya inference per candidate file per query (~0.9 s CPU / ~0.12 s
   GPU each). It adds latency and infra, though **no agent output tokens**.

**If pursued**, the recommended shape is:
- **Guarded fusion**, `score = w·norm(scubiee) + (1−w)·laya_full_file`, w≈0.5–0.7, applied only to
  the **file** state, and only as a *tie-break re-order* of Scubiee's top-N (never a replacement).
- **Normalize/clip Scubiee capability scores** before fusion (the `model_cache.py:79.7` case).
- **Run it after widening recall**, and re-measure — a reranker becomes more valuable once more of
  the true files are actually in the pool.
- Treat it as an **opt-in precision booster** for ambiguous multi-file tasks, not a default stage.

Bottom line: **Laya is a plausible precision tie-breaker via fusion, worth a follow-up once
first-stage recall is improved, but the current file-level gain is too small — and too dependent
on retrieval it cannot fix — to justify adding it as a mandatory second-stage reranker today.**

---

## Reproduce

```
laya_bench/rerank/
  build_tasks.py        # mine 18 multi-file tasks → tasks.json
  tasks.json            # tasks + verified relevant_files
  baseline_maps.json    # Scubiee production `map` (k=25) per task, file-aggregated
  run_rerank_eval.py    # Laya rerank + fusion + top-K + metrics (arg: cpu|dml)
  analyze_rerank.py     # helped/hurt examples + ceiling stats
  results/
    rerank_raw.json      # per-task: baseline order, laya scores (3 variants), every config's order+metrics
    rerank_summary.json  # aggregate table, latency, movement, retrieval ceiling
    analysis.json        # helped/hurt breakdown
```

Baseline was captured from the live Scubiee `map` MCP tool (session `laya-rerank-exp`, k=25);
`build_tasks.py` regenerates the task set; `run_rerank_eval.py` reproduces the Laya stage from the
recorded baseline without touching production retrieval.

### Threats to validity

- **Weak labels:** relevant = "files the commit changed"; a semantically relevant file the commit
  didn't touch counts as a distractor, slightly under-crediting Laya.
- **Task text = commit message**, occasionally naming the culprit file/symbol (some tasks are
  easier than a real vague issue; some, like the CLI-cluster and status-flag tasks, are genuinely
  hard).
- **Baseline pool capped at k=25** (the `map` tool's max), so a few relevant files may exist just
  beyond the cutoff; this is exactly the recall ceiling the report flags.
- **CPU scoring** for stability; latency would be ~8× lower on the GPU.
