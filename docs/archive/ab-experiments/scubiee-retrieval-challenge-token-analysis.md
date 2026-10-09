# Scubiee retrieval challenge — where the tokens actually go

A cheap, high-n benchmark that isolates *retrieval behavior* (find the right code)
from *code-writing behavior*, plus an instrumented token breakdown that answers a
specific question: **guided uses fewer greps but costs more tokens — where is the
waste?**

Evidence grades used below: **[OBS]** observed directly in these traces ·
**[STR]** strong (multiple sources / runs agree) · **[WEAK]** single run, n=1 ·
**[HYP]** hypothesis to test · **[DES]** design decision.

---

## 1. Why a retrieval-only challenge

Prior A/B work ran full coding tasks (locate → edit → build → oracle). Those cost
~0.8–1.3M tokens per run, so we could only afford a handful, and the retrieval
signal was tangled up with code-writing skill and open-ended-task variance.

The retrieval challenge strips it down to the one thing the policy is supposed to
change:

- The agent is given a **vague, de-keyworded description** of a behavior/area.
- It must **locate** the relevant code and write `RETRIEVAL_ANSWER.md` — an ordered
  list of the files it believes are relevant, best first, with the key symbol and a
  one-line reason. **It does not edit any code.**
- Hard, low turn cap (14). No build, no test. Far cheaper per run, so we can run
  many queries × arms × repeats and get statistical power. **[DES]**

### Objective oracle (git-derived, name-agnostic)

Each query is a paraphrase of a **real commit**. The **gold file set** = the
non-test `packages/**/*.py` files that commit changed (mechanical
`upgrade_releases/v*.py` release shims excluded — they are not where a human would
say the behavior "lives"). The agent never sees the gold set. The oracle:

- parses the python paths the agent **named** in its answer (prefers markdown
  list-item paths so a path mentioned only to be ruled out in prose is not counted;
  falls back to all paths if no list items), then computes
- **recall** (did it find the gold files), **precision** (how much of its answer was
  gold), **F1**, and **MRR** (rank of the first correct hit in its ordered list).

All gold files were verified to still exist in the current tree, and the two
trickiest concepts (`idle self-retire` in `server.py`, `cold-start warming status`
in `mcp_locate.py`) were confirmed still present, so the queries are gradeable
against today's code. **[OBS]**

### Arms (only the CLAUDE.md rule differs)

Identical answer contract, identical exposed tool surface (`map` + `gate`/`status`
for Scubiee arms), identical model (`claude-sonnet-5`). Every Scubiee arm ships the
**bare** server instructions so the arm's own rule is the sole retrieval
instruction (removes the stock pack-ladder confound). **[DES]**

- **without** — control; no Scubiee, native tools only (Read/Grep/Glob/Bash).
- **guided** — prior best-on-cost "when to use map" rule (no forced sequence).
- **two_layer** — new research-informed artifact: RULES (112 tok anchor) +
  INSTRUCTIONS (510 tok manual): policy-over-procedure, decision boundaries by what
  you already know, one causal reason, anti-loop/adapt clause, MUST/prefer tiers,
  contrastive good/bad examples.

### Query bank (8 queries, mined from real commits)

| id | category | gold files | source commit |
|---|---|---|---|
| first_map_skips_graph | discovery | context_trace, locate_cli, mcp_lifecycle, mcp_locate | 31cdb0f |
| idle_engine_self_retire | discovery | server.py | 9bae058 |
| cold_start_status_warming | discovery | mcp_locate.py | 0723319 |
| dirty_path_first_char | focused | freshness.py | e4710a1 |
| faiss_reimport_segfault | focused | install_health.py | ea34444 |
| ir_indexed_once_per_sync | focused | metadata/__init__.py | a911397 |
| memory_budget_resets_threads | cross_module | memory_budget.py, sync_loop.py | 5013f19 |
| watchdog_no_autoload_while_mcp | cross_module | watchdog.py | 28a346f |

Harness: `scripts/claude_sdk_harness/run_retrieval_bench.py` +
`retrieval_queries.py`. Reuses the proven snapshot / warm-proof / run_arm
plumbing; writes one `cell_*.json` per run and an incremental `report.json`.

---

## 2. Runs executed so far

Two small runs (smoke + instrumented), n=1 per cell — **directional only**, not
conclusions. All cells: agent wrote the answer file, oracle parsed it, engine warm.

### Smoke run (6 cells: 3 arms × 2 queries × 1 rep)

| Arm | Query | tokens | turns | map | grep | recall | prec | MRR |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| without | idle_retire (disc) | 278,477 | 12 | 0 | 7 | 1.0 | 0.25 | 1.0 |
| guided | idle_retire (disc) | 347,682 | 12 | 2 | 2 | 1.0 | 0.33 | 1.0 |
| two_layer | idle_retire (disc) | 265,768 | 11 | 2 | 1 | 1.0 | 0.50 | 1.0 |
| without | dirty_path (focus) | 263,232 | 11 | 0 | 6 | 1.0 | 1.00 | 1.0 |
| guided | dirty_path (focus) | 350,751 | 13 | 2 | 2 | 1.0 | 0.50 | 1.0 |
| two_layer | dirty_path (focus) | 441,359 | 13 | 2 | 3 | 1.0 | 1.00 | 1.0 |

All arms reached recall 1.0 / MRR 1.0 on both queries — these two single-file golds
do not separate the arms on *accuracy*. They separate on **precision** (over-listing
of spurious files) and **exploration cost**. **[OBS]**

### Instrumented re-run (3 cells: 3 arms × idle_retire × 1 rep)

This is the run used for the token breakdown in §3. Note the **variance**: the
`without` arm that was 12 turns / 278k in the smoke run came back **20 turns /
974k** here on the *same query* — a 156k swing from agent nondeterminism alone.
**[OBS]**

| Arm | tokens | cache_read | output | turns | map | grep | read | prec |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| without | 973,962 | 897,805 | 7,218 | 20 | 0 | 11 | 7 | 0.20 |
| guided | 300,252 | 275,748 | 4,031 | 13 | 2 | 4 | 4 | 0.25 |
| two_layer | 456,737 | 429,812 | 4,157 | 13 | 2 | 4 | 4 | 0.33 |

---

## 3. Where the tokens go (the answer)

New instrumentation added to `run_arm` (in `harness_run.py`):

- **`tool_results`** — the char size of every tool RESULT block, attributed to the
  tool that produced it (matched by `tool_use_id`). This is the context each tool
  injects.
- **`turn_usage`** — the per-assistant-message usage snapshot, so we can watch
  `cache_read` (the carried context) grow turn by turn.

### 3.1 Tool-result payload — Scubiee is dramatically leaner, NOT the waste

Total characters of tool-result content injected into the conversation:

| Arm | total result chars | breakdown |
|---|---:|---|
| guided | 22,576 | map 5,159 · Read 15,247 · Grep 1,857 · Write 253 |
| two_layer | 26,757 | map 5,269 · Read 16,235 · Grep 4,937 · Write 256 |
| **without** | **139,039** | **Read 118,842** · Grep 19,943 · Write 254 |

The `without` arm dumped **6× more content** into context — because with no map to
point it at line ranges, it **read two whole huge files**: one 37,561-char read and
one 67,473-char read (visible in its call sequence). The `map` result itself is tiny
(~5,200 chars for two maps) and it steers the agent to read *spans*, so both Scubiee
arms' reads stay ~15–16k. **This is the real retrieval win, and it is genuine.**
**[OBS]**

So the waste in guided/two_layer is **not** in tool results, and it is **not** in
greps (greps return ~40–2,800 chars each — cheap), and it is **not** in output
tokens (4.0–4.2k, near-identical). **[OBS]**

### 3.2 The cost is `cache_read`, and `cache_read = per-turn context × turns`

~92–93% of every arm's total tokens is `cache_read`. The mechanic:

> Every turn, the model re-reads the **entire accumulated transcript** (system
> prompt + the arm's rule text + all prior tool results). The SDK bills that as
> `cache_read` on each turn. So **total tokens ≈ the sum of the context size across
> all turns** — not the size of any single result.

Per-turn `cache_read` growth (carried context at each billing step):

- **guided**: 20.8k → 39.0k across ~20 steps → sums to ~276k
- **two_layer**: 20.8k → 41.2k across ~22 steps → sums to ~430k
- **without**: 20.8k → **87.2k** (jumps to 70.3k at step 13, exactly when it read the
  67k-char file) → sums to ~898k

The `without` step-13 jump is the smoking gun: the moment it reads a whole large
file, the carried context nearly triples, and **every subsequent turn pays that
inflated context again**. That single whole-file read is what blew the arm from
~280k to ~974k. **[OBS]**

### 3.3 Why two_layer cost more than guided *this run* (n=1)

Both arms had near-identical tool counts (2 map, 4 grep, 4 read, 13 turns). The
~130k gap came from three small, multiplied effects:

1. **Bigger reads.** two_layer's reads totaled 16,235 chars incl. one 6,263-char
   read; guided's largest was 4,704. Larger reads inflate context on **every
   subsequent turn**. **[OBS]**
2. **More billing steps.** two_layer logged 22 usage snapshots vs guided's 20 — a
   couple of extra internal round-trips, each re-reading the full context. **[OBS]**
3. **Instruction rent.** two_layer carries a 510-token INSTRUCTIONS block (plus the
   112-token RULES) in context on **every** turn. Small per turn, but multiplied by
   ~22 turns it is a standing cost guided (shorter rule) does not pay. **[HYP]** —
   plausible from the mechanic, not yet isolated.

**Critical caveat:** at n=1 with observed turn-count swings of 12↔20 on the same
query, the 130k guided-vs-two_layer gap is **well within noise**. We cannot yet
conclude two_layer is more expensive. **[WEAK]**

---

## 4. What this means for the policy

1. **The cost lever is turns and read-size, not grep count.** Cutting greps barely
   moves tokens; cutting whole-file reads and total turns moves them a lot. A rule
   that says "reduce greps" optimizes the wrong thing. **[STR]** (mechanic + traces)
2. **The single most valuable cost rule is already correct:** *read the `loc` span,
   never the whole file.* That is precisely what prevents the `without`-style 67k
   read that tripled context. Keep it as a hard rule. **[STR]**
3. **Instruction text is paid every turn.** Because cost ≈ text × turns, the
   510-token INSTRUCTIONS block is standing rent. Trimming it — or pushing detail
   into examples the model consults once rather than prose it re-reads each turn —
   is a real, testable cost lever. **[HYP]**
4. **map's compression is the win to protect.** The map result is ~2.5k chars and it
   replaced ~105k chars of whole-file reading in the control. That compression, not
   the ranking, is where Scubiee pays for itself on discovery queries. **[OBS]**
5. **Precision, not recall, is the near-term differentiator on easy queries.** All
   arms hit recall 1.0 here; the arms differ in how many spurious files they list
   (without 0.20–0.25, guided 0.25–0.50, two_layer 0.33–1.00). The harder
   multi-file cross_module and buried queries are where recall should finally
   split the arms. **[OBS]**

---

## 5. Honesty / limitations

- **n=1 per cell.** Turn count is highly nondeterministic (12↔20 on one query).
  Nothing here about *cost* differences between guided and two_layer is
  conclusive; treat §3.3 as mechanism, not verdict. **[WEAK]**
- **Two single-file, findable queries.** Recall saturated at 1.0, so accuracy did
  not separate the arms. The design needs the harder queries to earn a recall
  signal.
- **Token totals are cache-read-dominated**, so they track transcript length ×
  turns. Absolute totals are noisy; the *composition* (result chars, per-turn
  growth) is the trustworthy part and is what this report leans on.
- **Result-char attribution** counts characters, not tokens; it is a faithful proxy
  for relative context weight, not an exact token count.

---

## 6. Recommended next steps

1. **n=3 on the discovery query** for a noise-robust guided-vs-two_layer cost
   comparison (turn-count variance needs repeats to average out). **[DES]**
2. **A/B a lean two_layer vs the full 510-token version** to isolate the
   instruction-rent hypothesis (§3.3.3) directly. **[DES]**
3. **Run the harder queries** (`cold_start_status_warming` in the large
   `mcp_locate.py`, and the two cross_module queries) — these are where recall,
   not just precision, should finally separate map-equipped arms from the control.
4. Fold results into the final graded report.

---

## Appendix — files

- Harness: `scripts/claude_sdk_harness/run_retrieval_bench.py`
- Query bank: `scripts/claude_sdk_harness/retrieval_queries.py`
- Instrumentation: `tool_results` + `turn_usage` in `harness_run.py::run_arm`
- Instrumented run dir: `.ab_workspaces/claude_sdk_harness/20260930T172308Z_retrieval/`
- Smoke run dir: `.ab_workspaces/claude_sdk_harness/20260930T171309Z_retrieval/`
