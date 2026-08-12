# Research and Experiments

This document covers the experimental infrastructure, what was tested, and what findings shaped the current implementation.

## Core hypothesis

Context Engine exists to prove that **semantic search + structural graph gives coding agents better code context with fewer tokens than blind grep + full-file reads**. The experiments measure token efficiency (lower = better) and retrieval quality (correct files found).

## Test corpus

Almost all experiments run against `testdata/frontend-mcp/` — a synthetic frontend MCP project with a known architecture:
- `agent_guidance.py` — what the agent should do when sessions disappear
- `browser_session_manager.py` — lease/queue owner preventing tools from sharing a browser
- `dispatch_registry.py` — maps tool names to callable handlers
- Plus SEO, Figma, dribbble directories that serve as distractors

This repo has ~3148 chunks when fully indexed.

## Experiment categories

### 1. Embedding quality benchmarks (offline, no LLM)

These measure retrieval recall/precision of the embedding+index system itself, without an actual agent in the loop.

**Scripts:** `scripts/bench_*.py`

| Experiment | Question | Finding |
|-----------|----------|---------|
| `bench_mix_seq_ab` | Does seq length matter? (128 vs 512) | No — seq=128 ≈ seq=512 on mix-compressed text |
| `bench_budget_alloc` | Given 450 chars, how to allocate? | mix > budget_c > budget_b > budget_a > card > skeleton |
| `bench_size_ladder` | How small before quality drops? | Knee at ~300 chars. Below 250, soft R@5 falls off |
| `bench_difficult_compare` | Hard/adversarial queries at different sizes? | Hard symbol locate is budget-invariant down to 200; soft NL is sensitive |

**Metrics:** Recall@1/5/10, MRR, nDCG@10 against gold query sets (52 soft + 12 hard queries).

**Key findings shipped into production:**
- Compression mode: `mix` (card core + importance body fill)
- Default budget: 512 chars max (conservative; could ship 300)
- Sequence length: 512 (safe default; 128 also works)

### 2. Session token A/B (deterministic, no LLM)

**Script:** `scripts/session_ab_realistic.py`

Simulates a multi-turn coding session with scripted agent behavior. Two arms:
- **graphify_grep:** Graph neighbors + term grep + full-file reads (8000 chars each)
- **context_engine:** Semantic search + file outlines + pointer previews (500-600 chars each)

Three turns: T1 (explore + edit), T2 (follow-up same area), T3 (related architecture).

**What it measures:** Total tokens added to context, number of operations (greps, searches, file reads, outlines), latency.

**Core insight:** On follow-up turns (T2), grep re-reads entire files while CE reuses session memory with compact outlines. The token gap is largest on T2. CE uses ~60-70% fewer context tokens across a 3-turn session.

### 3. Live agent A/B tests (real LLM, OpenCode/Cursor)

These run actual AI agents against the test corpus with different retrieval tools available.

#### opencode_raw_vs_ce (the cleanest test)

**Script:** `scripts/experiments/opencode_raw_vs_ce/run.py`

Two arms:
- **raw:** Only native read/grep/glob — no MCP, no CE
- **ce_search:** CE search MCP + native read/grep/glob

Both use `opencode run --format json --auto --pure` with vague soft queries. Measures tokens_total from `step_finish` events, tool calls (MCP vs builtin), rubric pass rate (must_touch/must_avoid files).

**Winner criterion:** Lowest tokens among arms that pass ≥50% rubric.

#### opencode_soft_ab

**Script:** `scripts/experiments/opencode_soft_ab/run.py`

Three arms: graphify vs CE R_plan vs CE D_rerank. Agent has read/grep/glob plus one MCP (CE or Graphify). System hint encourages (soft) or requires (high) MCP usage.

#### opencode_mcp_ab

**Script:** `scripts/experiments/opencode_mcp_ab/run.py`

MCP-only arms (all native tools denied): graphify, d_rerank, ce_nav, d_channel_best. Tests raw retrieval capability when the agent has no fallback.

### 4. Cursor SDK trials

**Scripts:** `scripts/experiments/sdk_mcp_smoke.py`, `scripts/experiments/sdk_mcp_dev_trial.py`

Earlier experiments using the Cursor SDK (now migrated to OpenCode):
- **Smoke test:** Send one vague prompt, observe which MCP tools the agent calls, score rubric.
- **Dev trial:** Full coding task — agent gets an isolated workspace, must implement a feature using the assigned retrieval tool. Measures: tool usage, diff quality (multi-file implementation), test creation.

These are being migrated away from Cursor SDK toward OpenCode CLI for reproducibility.

### 5. SEIR embedding experiments

**Package:** `packages/seir/`

Explores alternative text representations for code spans before embedding:
- `baseline` — what CE currently embeds (mix-compressed)
- `ast_tree` — AST structural skeleton
- `rels` — relationships text
- `semantic` — rule-based semantic card (purpose, inputs, outputs, trust boundaries)
- `importance` — IDF-scored body lines
- `mix_rels` — combined

Used by `scripts/seir_ab_bench.py` and `scripts/seir_matrix_bench.py` to evaluate which representation produces the best retrieval quality.

## Experimental infrastructure patterns

### Mission files

Each OpenCode experiment has a `mission.json`:
```json
{
  "title": "...",
  "repo": "testdata/frontend-mcp",
  "turns": [
    {
      "id": "T1",
      "prompt": "vague natural language task description...",
      "must_touch": ["agent_guidance.py", "browser_session_manager.py"],
      "must_avoid": ["seo/", "dribbble/"]
    }
  ]
}
```

### Scoring

- **must_touch:** The agent's final answer must mention these files (case-insensitive substring match).
- **must_avoid:** The agent's answer must NOT mention these paths (prevents rabbit-holing into distractors).
- **rubric_pass:** Both must_touch and must_avoid satisfied.
- **tokens_total:** Sum of `step_finish` token counters across all turns.
- **Winner:** Lowest tokens among arms with rubric_rate ≥ 50%.

### Daemon management in experiments

CE arms need a warm daemon. The harnesses:
1. Call `force_restart_daemon(repo)` with the desired `CTX_RETRIEVE` mode.
2. Call `EngineClient().open_repo(repo, wait=True)` to ensure the index is loaded.
3. Verify the retrieve mode with a test search.
4. Then run the OpenCode subprocess.

### Arm isolation

Each arm gets its own `opencode.json` config file specifying:
- Which MCP servers are available (and which are disabled)
- Which native tools are allowed (read/grep/glob) or denied (edit/bash)
- Environment variables for the MCP server (CTX_REPO, CTX_RETRIEVE, CTX_ENGINE_URL)

## Previous experiments vs current system

| What was tried | Outcome | Status |
|---------------|---------|--------|
| Pure dense retrieval (no BM25/graph) | Misses exact symbols | Abandoned — conductor fusion shipped |
| Pure graph retrieval (Graphify only) | Poor on vague queries | Abandoned — fused into conductor |
| Multiple MCP tools (nav surface: 6 tools) | Agents confused by choice | Simplified to read surface (3 tools) |
| Large excerpt bodies in search results | Token waste on wrong files | Replaced with handles + session dedup |
| LLM-based query distillation | Expensive, marginal gain | Optional (off by default), heuristic plan instead |
| Full-file reads on every hit | Huge token cost on follow-ups | Replaced with outlines + pointer previews |
| Cursor SDK for A/B testing | SDK instability, hard to reproduce | Migrating to OpenCode CLI |
| CBM (Codebase Memory) graph tools | Complementary to CE search | Available as hybrid_cbm facade |
| Different embed budget allocations | `mix` wins over pure presets | Shipped as default |
| Embedding seq 128 vs 512 | Nearly identical quality | Defaulting to 512 (safe) but 128 is fine |

## Research data

Stored in `research/`:
- Gold evaluation sets (`ctx_gold.json`, `ctx_sealed_final.json`)
- Before/after comparisons (`locate_quality_before/after.json`)
- Trace evaluations (`ctx_trace_dev.json`)
- Agent contract evaluations (`agent_contract_eval.json`)
- Hyperparameter sweep cache (`sweep_cache.pkl`)

## How to run experiments

```bash
# Embedding quality (offline, fast)
.\.venv\Scripts\python.exe -u scripts\bench_size_ladder.py

# Session token comparison (offline, fast)
.\.venv\Scripts\python.exe -u scripts\session_ab_realistic.py

# Live agent A/B (requires OpenCode + API key + daemon running)
.\.venv\Scripts\python.exe -u scripts\experiments\opencode_raw_vs_ce\run.py

# Dry run (no API calls, just validate config)
.\.venv\Scripts\python.exe -u scripts\experiments\opencode_raw_vs_ce\run.py --dry-run
```

## What we're trying to learn

1. **Token efficiency:** Does CE help agents complete tasks with fewer total tokens than raw grep?
2. **Retrieval precision:** Does CE find the right files more reliably than grep?
3. **Follow-up efficiency:** Does session memory (outlines, handles) beat cold rediscovery on turn 2+?
4. **Embedding optimization:** What's the minimum information density that preserves retrieval quality?
5. **Tool design:** How many tools should the MCP expose? Which combinations reduce agent confusion?
6. **Retrieval architecture:** Does fusing graph + BM25 + dense outperform any single channel?

The current system represents the answers we've converged on so far. The experiment infrastructure remains active for continued iteration.
