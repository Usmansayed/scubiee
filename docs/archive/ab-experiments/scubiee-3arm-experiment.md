# Claude Code with vs. without Scubiee — 3-arm token experiment

Does giving Claude Code even a *limited* Scubiee toolset reduce the context/tokens it spends on
the same coding task? Three arms, one identical vague task, same model, same starting tree.

## Setup

- **Model:** `claude-sonnet-5` (via the Claude Agent SDK), real `model_usage` token accounting
  (input + output + cache-read + cache-creation, summed across all billed models incl. the
  internal Haiku helper).
- **Task:** one vague, human-sounding request (a Slack-style ask to make a token-savings
  comparison "cache-aware"). **No file names, symbols, or formulas** in the prompt — so the agent
  must actually understand an unfamiliar `packages/` tree, not grep a leaked keyword. Graded by a
  hidden behavior oracle (never shown to the agent).
- **Identical conditions:** all three arms start from a **byte-identical** git snapshot of
  `packages/` (verified equal trees), same model, same system prompt, same task.
- **Tool restriction mechanism (as requested):** the Scubiee MCP server still **exposes all
  tools**; each arm is limited two ways — (1) the SDK `allowed_tools` allow-list, and (2) an
  **explicit rule appended to the workspace `CLAUDE.md`** telling the agent exactly which tools it
  may use for that run.

**Arms**
- **A — Without Scubiee:** native tools only (Read/Grep/Glob/Edit/Write/Bash/TodoWrite).
- **B — Scubiee map only:** native + Scubiee `map` (plus `gate`/`status` health). Rule: use `map`
  to locate, then Read the exact spans; no other Scubiee tool.
- **C — Scubiee map + session context:** native + `map` + the session-context recall tools
  `workspace` (pins/heatmap/already-seen) and `expand` (re-open a stored span), plus `gate`/`status`.

## Results

| Metric | A: Without | B: map only | C: map + session |
|---|---:|---:|---:|
| **Total tokens** | 1,422,730 | **774,797** | 1,472,026 |
| **% vs without** | — | **−45.5%** | +3.5% (worse) |
| Input tokens | 1,181 | 1,157 | 1,187 |
| Output tokens | 21,574 | 16,420 | 19,093 |
| Cache-read tokens | 1,337,590 | 725,750 | 1,409,009 |
| Tool calls (all) | 29 | 18 | 32 |
| Native Read/Grep/Glob | 16 | **3** | 18 |
| Scubiee calls | 0 | 3 | 4 |
| Scubiee tools used | — | gate, map | gate, map, status |
| Turns | 30 | 19 | 33 |
| Wall time | 260 s | **148 s** | 189 s |
| **Agent source edits** | 1 file (`token_meter.py`) | 1 file (`token_meter.py`) | 1 file (`token_meter.py`) |
| **Task success (oracle)** | ✓ (1.0) | ✓ (1.0) | ✓ (1.0) |

> **Data-quality note on "files modified":** the raw git diff showed ~233 changed paths for the
> Scubiee arms, but those are **Scubiee's own `.scubiee/cache/` artifacts** (parse-cache pickles,
> composite-edge cache) written into the workspace when `map` ran — **not agent edits**. The real
> agent change in every arm is exactly one source file, `packages/pipeline/token_meter.py`
> (+84 lines). The table reports the corrected count. A production integration should gitignore
> `.scubiee/` (it already is in the main repo) so this never pollutes a diff.

## What happened

- **`map` alone cut total tokens ~45%** (1.42M → 0.77M) and wall time ~43% (260s → 148s), while
  producing the same correct result. The mechanism is visible in the trace: native discovery
  collapsed from **16 Read/Grep/Glob calls → 3**, and turns from **30 → 19**. `map` pointed the
  agent at `token_meter.py` directly, so it stopped grep-walking the tree. Because total tokens are
  dominated by **cache-read** (every turn re-sends the transcript), fewer discovery turns ≈
  proportionally fewer tokens — cache-read fell 1.34M → 0.73M.
- **`map` + session context was a wash (+3.5%, i.e. slightly worse).** Crucially, the agent
  **never actually called `workspace` or `expand`** (tools used: gate, map, status). So arm C
  added the extra rule text (a fixed per-turn token tax) and the model reverted to native
  discovery (18 Read/Grep/Glob, 33 turns) — it did not exploit the session-recall tools on this
  single-shot task. Offering tools the agent doesn't reach for adds cost without benefit.
- **All three succeeded** (behavior oracle 1.0), so the token difference is a genuine
  efficiency delta, not a quality trade-off.

## Interpretation

This directly contradicts the earlier *all-tools* finding (see
`docs/scubiee-token-ab-deep-dive.md`, where the full Scubiee surface cost **more** tokens because
the agent used `map` *additively* — mapping and then grepping the same thing anyway). The
difference here is the **explicit "map only, then Read the spans" rule**: constraining the agent to
`map` for discovery removes the additive-grep waste and the map genuinely replaces the grep-walk.

**The lever is not "how many Scubiee tools" — it's "does the agent replace native discovery with
one good locate call."** A tight map-only policy does that; a broader toolset invites the agent to
keep its old habits (and pay for both).

Caveats worth stating:
- **n = 1 task, 1 run per arm.** Sonnet's agentic behavior is stochastic; token totals can swing
  run-to-run (the deep-dive saw ±tens of percent). The 45% is a strong single signal, not a
  stable mean — it needs repeats across tasks/seeds to be a headline number.
- The task was deliberately **map-favorable** (a genuinely buried target, no grep-able keywords).
  A keyword-leaky task would let native grep win in one shot and erase the gap.
- Session-context arm's null result is partly "the agent didn't use it" — a multi-turn or
  resumed task might exercise `workspace`/`expand` and change the verdict.

## Answer

**Yes — even the limited Scubiee setup (map-only) reduced context/token usage substantially on
this task: −45% total tokens, −43% wall time, same correct outcome, by replacing 16 native
discovery calls with 3.** The **map-only** constraint is the winner. Adding the session-context
recall tools did **not** help here (the agent ignored them and paid the extra rule tax), so
"more limited" beat "less limited."

Recommended next step to harden this: repeat map-only vs without across ~5–10 tasks and 2–3 seeds
each to get a mean ± spread, and re-test the session-context arm on a **multi-turn** task where
recall tools can actually pay off.

## Reproduce

```
scripts/claude_sdk_harness/
  run_3arm.py          # 3-arm orchestrator (this experiment)
  harness_core.py      # snapshots, Scubiee MCP wiring, real token accounting
  harness_run.py       # run_arm (allowed_tools + scubiee_tool_subset restriction)
  harness_task.py      # the vague task + hidden behavior oracle
  harness_preflight.py # static + warm-proof gates
python scripts/claude_sdk_harness/run_3arm.py --preflight-only   # validate wiring (cheap)
python scripts/claude_sdk_harness/run_3arm.py                    # full 3-arm run
```
Raw per-arm traces + REPORT.md land in `.ab_workspaces/claude_sdk_harness/<run_id>_3arm/`.
Tool restriction is enforced by `allowed_tools` (SDK) **and** an explicit rule in each arm's
`CLAUDE.md`; the MCP server exposes all tools regardless (arms differ only in what they're allowed
and told to use).
```
