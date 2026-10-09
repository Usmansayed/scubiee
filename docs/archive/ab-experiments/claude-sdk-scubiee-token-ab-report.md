# Does Scubiee reduce token usage? — Claude Code SDK A/B benchmark

Model under test: **`claude-sonnet-5`** (Sonnet 5), driven through the
**Claude Agent SDK** (`claude-agent-sdk` 0.2.161 → Claude Code CLI 2.1.283).
Harness: `scripts/claude_sdk_harness/`. All numbers below come from the SDK's
real per-model token accounting (`ResultMessage.model_usage`), not estimates.

---

## 1. Harness setup

A new harness was built specifically for Claude Code via its SDK, reusing the
architecture of the existing Kiro harness (`scripts/kiro_credit_harness.py` +
`kiro_mcp_ab_dev_eval.py`) — snapshot → identical baseline → warm proof → live
tool proof → run both arms → score → compare — but replacing that harness's
char/4 token *estimate* with the Claude SDK's *real* usage numbers.

Files:

| File | Role |
|---|---|
| `harness_core.py` | Auth, Scubiee stdio MCP config/env, isolated git snapshots, token accounting |
| `harness_run.py` | `run_arm()` — drives `claude_agent_sdk.query`, captures usage + every tool call |
| `harness_task.py` | The two benchmark scenarios, neutral prompts, and hidden pytest oracles |
| `harness_preflight.py` | Static checks + zero-token Scubiee warm proof |
| `run_harness.py` | Orchestrator + gates + comparison + report |
| `_probe_auth.py` | Standalone auth/model probe |
| `_probe_scubiee_mcp.py` | Standalone raw-MCP Scubiee warm proof |

**Two isolated arms, identical except for Scubiee.** Both arms run in
byte-identical git snapshots (verified: `git HEAD^{tree}` equal). The ONLY
differences applied to the WITH arm are:

1. `mcp_servers={"scubiee": <stdio bridge>}` + `mcp__scubiee__*` in `allowed_tools`;
2. the real Scubiee GATE policy text appended to the workspace `CLAUDE.md`
   (generated from the product source `pipeline.rules_installer.managed_gate_mcp_only_rule_body`).

`strict_mcp_config=True` guarantees the WITHOUT arm cannot see Scubiee even
though the machine has a global Scubiee config. Scubiee's locate is pointed at
the already-warm parent index (`CTX_REPO` = repo root, 7 869 chunks) so the
snapshot needs no cold index build — the same technique the Kiro harness uses.

**Token accounting.** For each run the harness sums `inputTokens`,
`outputTokens`, `cacheReadInputTokens`, and `cacheCreationInputTokens` across
**every** model in `model_usage` (Sonnet 5 plus the small `claude-haiku-4-5`
that Claude Code uses internally), giving a true total. Per-model and cache
breakdowns are retained. Tool calls are counted from `ToolUseBlock`s and split
into Scubiee (`mcp__scubiee__*`) vs native.

---

## 2. Preflight tests and results

All gates passed before any benchmark run (run `20260928T232216Z`).

| Gate | What it proves | Result |
|---|---|---|
| **static** | OAuth token present; SDK imports; `claude` CLI present; Scubiee bridge present; engine warm (`ok && dense_ready && warm_ready`, 7 869 chunks); project_id `ce_3536…` | **OK** |
| **auth probe** | Token authenticates; SDK launches Claude Code; model resolves to `claude-sonnet-5` (`canonicalModel: claude-sonnet-5`); real usage returned | **OK** (`answer: "PONG"`, `sonnet_used: true`) |
| **warm proof** (0 tokens) | Raw MCP stdio to the exact WITH-arm bridge config: `initialize`, `tools/list` (all 8 tools), `status` (warm), `gate`, `map` (4 cards), `pack_context` (7 heatmap rows) | **OK** |
| **snapshot** | WITH and WITHOUT trees byte-identical | **OK** (`identical_tree=True`) |
| **live capability probe** | A real Sonnet 5 run that must *see the rules* and *actually drive Scubiee* | **OK** |

Live probe detail (verified from the tool trace, not just the model's words):

```json
{ "saw_rules": true,
  "rules_phrase": "MUST Use Scubiee MCP for locate",
  "tools_available": true, "status_ok": true, "map_ok": true,
  "model_used": "claude-sonnet-5", "scubiee_calls": 2,
  "scubiee_tools_used": ["status", "map"] }
```

This confirms the whole stack is functional: auth, SDK, model, repo access,
Scubiee MCP, rules visibility, and accurate token capture.

**One environment issue found and fixed during preflight hardening:** the base
conda env has a broken `opentelemetry` pytest plugin that crashes test
collection; the oracle scorer runs with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
Also fixed: a binary `git archive` stream was being decoded as text
(UnicodeDecodeError) — now read as bytes. These were harness bugs, not result
contamination; every reported run completed cleanly afterward.

---

## 3. Exact benchmark scenario / prompt

Two scenarios, each a real coding change with a **hidden** deterministic pytest
oracle the agent never sees. The prompts describe the *outcome and contract*
but name **no tool, no search strategy, and no file path** — the agent decides
how to find and change the code. The prompt is identical for both arms.

**Scenario 1 — scoped (`packages/pipeline`, ~130 modules).** Add cache-aware
token accounting to the token-comparison module (`token_meter.py`, not named in
the prompt): an optional `cached_tokens` field on the per-arm result dataclass,
an `effective_tokens` property (`round((tokens-cached)+0.1*cached)`, clamped),
`effective_saved`/`effective_pct_saved` on the comparison dataclass, and three
new totals in the summary dict. Oracle: 7 tests.

**Scenario 2 — broad (all of `packages/`, 11 packages).** Find the small
text-density helper module (`seir/caps.py`, not named) and add a
`truncate_middle(text, max_chars=DEFAULT_MAX_CHARS)` that keeps both ends and
elides the middle to an exact length with a specified head/tail split. Oracle:
6 tests. This scenario deliberately makes naive grep noisy ("truncate",
"token", "chars" appear across many modules).

Fairness: the Scubiee arm receives **no** extra task information — only the
Scubiee tooling and its standard GATE rules. Same prompt, same starting tree,
same model, same permission mode (`acceptEdits`), WITHOUT run first each time.

---

## 4. Baseline results (Run A — no Scubiee)

Per run, total tokens (real, all models), tool calls, success:

| Run | Scenario | Total tokens | Output | Cache-read | Tool calls | Oracle |
|---|---|---:|---:|---:|---:|---|
| 233502Z | 1 | 252,761 | 5,454 | 306,853 | 7 | 7/7 ✅ |
| 234149Z | 1 | 251,564 | 4,792 | 231,270 | 7 | 7/7 ✅ |
| 234440Z | 1 | 216,186 | — | — | 6 | 7/7 ✅ |
| 233940Z | 2 | 190,835 | 1,957 | 179,902 | 6 | 6/6 ✅ |
| 234657Z | 2 | 161,671 | — | — | 5 | 6/6 ✅ |

Baseline behaviour was consistent: a precise `Grep` (e.g. `class.*Comparison|tokens_saved`,
`def truncate\(`), one `Read`, one or two `Edit`s, and a `Bash` test run.
**Baseline success: 5/5.**

---

## 5. Scubiee results (Run B — Scubiee enabled)

| Run | Scenario | Total tokens | Output | Cache-read | Tool calls | Scubiee calls | Oracle |
|---|---|---:|---:|---:|---:|---:|---|
| 233502Z | 1 | 352,289 | 5,935 | 365,538 | 9 | **0** | 7/7 ✅ |
| 234149Z | 1 | 402,339 | 6,284 | 372,865 | 12 | **4** (gate, map×2, status) | 7/7 ✅ |
| 234440Z | 1 | 310,634 | — | — | 8 | **0** | 7/7 ✅ |
| 233940Z | 2 | 115,474 | 1,326 | 104,470 | 3 | **0** | 6/6 ✅ |
| 234657Z | 2 | 177,716 | — | — | 5 | **0** | 6/6 ✅ |

**Scubiee-arm success: 5/5.** Critically, **the agent invoked Scubiee in only
1 of 5 runs.** In that one run it called `gate` + `map`×2 + `status` (after a
`ToolSearch`) and then **still ran `Grep` twice and `Read` to actually locate
and verify the code** — Scubiee was used *in addition to* grep, not instead.

---

## 6. Token comparison (absolute)

Aggregate across all 5 runs (Δ sign convention: **+ = Scubiee arm used MORE**):

| | Without Scubiee | With Scubiee | Δ |
|---|---:|---:|---:|
| **Total tokens (all runs)** | **1,073,017** | **1,358,452** | **+285,435** |

Per run:

| Run | Scenario | Without | With | Δ tokens | Δ % | Scubiee used? |
|---|---|---:|---:|---:|---:|:--:|
| 233502Z | 1 | 252,761 | 352,289 | +99,528 | **+39.4%** | no |
| 234149Z | 1 | 251,564 | 402,339 | +150,775 | **+59.9%** | **yes (4)** |
| 234440Z | 1 | 216,186 | 310,634 | +94,448 | **+43.7%** | no |
| 233940Z | 2 | 190,835 | 115,474 | −75,361 | **−39.5%** | no |
| 234657Z | 2 | 161,671 | 177,716 | +16,045 | **+9.9%** | no |

---

## 7. Percentage token change

- **Aggregate: +26.6%** — the Scubiee arm used **26.6% MORE** tokens overall.
- Scenario 1 (scoped): mean **+47.7%** (n=3, range +39.4%…+59.9%).
- Scenario 2 (broad): mean **−14.8%** (n=2, range −39.5%…+9.9%).
- The Scubiee arm used **more** tokens in **4 of 5** runs.

The single "saving" (−39.5%, run 233940Z) did **not** come from Scubiee: the
Scubiee arm never called Scubiee there and simply happened to converge in 3
tool calls vs the baseline's 6. That is run-to-run exploration variance, not a
Scubiee effect — the token total is dominated by `cache-read`, which scales
with the number of turns (each turn re-sends prior context from cache).

**No measured saving is attributable to Scubiee.**

---

## 8. Tool-call and context differences

- Under a **neutral prompt, Claude Sonnet 5 overwhelmingly prefers native
  `Grep`.** In 4/5 runs it ignored the available Scubiee tools entirely and
  found the target with one or two precise symbol/regex greps
  (`class.*Comparison|tokens_saved`, `def truncate\(`, `DEFAULT_MAX_CHARS`).
- **The Scubiee arm carries the GATE rules** in `CLAUDE.md`. That text is
  re-sent as cached context every turn, adding `cache-creation` +
  `cache-read` tokens on the WITH side even when Scubiee is never called. In
  the equal-tool-count run (234657Z, 5 vs 5 tools) this base overhead alone was
  **+9.9%**.
- **When Scubiee was used (234149Z), it was additive, not substitutive.** The
  agent ran `ToolSearch` → `gate` → `map`×2 → `status`, *then still grepped and
  read the file*. That added turns (13 vs 8) and made it the single most
  expensive run in the whole benchmark (+59.9%).
- Task quality was unaffected: **both arms passed the hidden oracle in all 5
  runs**, so Scubiee neither helped nor hurt correctness here.

---

## 9. Failures and anomalies

- **Scubiee under-utilisation is the headline anomaly:** despite the "MUST Use
  Scubiee MCP for locate" GATE (which the live probe proved the agent reads and
  can act on), the agent chose Scubiee in only 1/5 benchmark runs. The GATE
  itself permits grep for named symbols / known paths, and Sonnet 5's grep was
  precise enough that it self-selected the cheaper native path. This is a valid
  behavioural finding, but it means these tasks do **not** exercise Scubiee's
  intended value path (large, ambiguous, cross-module discovery).
- **Internal Haiku usage:** every run also billed a small amount of
  `claude-haiku-4-5` (~1.3–1.5k tokens) for Claude Code's internal bookkeeping.
  It is included in the totals and is ~equal across arms, so it does not bias
  the comparison.
- **Harness bugs found and fixed before trusting results:** (a) missing `os`
  import in the scorer; (b) `git archive` binary stream decoded as text; (c)
  the broken `opentelemetry` pytest plugin. Runs reported here all completed
  after these fixes; earlier crashed attempts were discarded.
- **Variance is large** relative to any Scubiee signal: baseline totals ranged
  161k–253k for the same tasks. With n=5 (1 Scubiee-active), this benchmark can
  say Scubiee did not *save* tokens here, but cannot precisely quantify a
  small effect in either direction.

---

## 10. Conclusion (strictly from measured results)

**On this benchmark, Scubiee did not reduce token usage — it increased it by
~26.6% in aggregate and in 4 of 5 runs, while task success was identical (5/5
both arms).**

The mechanism is clear from the traces: given a neutral prompt and precise
native grep, Claude Sonnet 5 mostly does not invoke Scubiee (1/5 runs), so the
Scubiee arm pays for the GATE rules' extra context with no offsetting retrieval
saving; and in the one run where Scubiee *was* used, it was layered on top of
grep rather than replacing it, making that run the most expensive of all.

Important scope limits on this conclusion:

- It holds for **well-specified changes to a single, findable module** — the
  regime where grep is already cheap and effective. It is **not** evidence
  about Scubiee's behaviour on large, vague, cross-repo discovery tasks where
  reading many wrong files would dominate the baseline; those tasks were not
  reached here because the agent didn't need broad discovery to succeed.
- The result is about **Scubiee as actually adopted by Sonnet 5 under a neutral
  prompt**, which is the fair question the experiment asked. If the goal is to
  measure Scubiee's ceiling, a follow-up should force tool usage or choose
  tasks grep genuinely cannot resolve cheaply, and run more replicates
  (n ≥ 10 per cell) to overcome the observed variance.

Everything needed to reproduce or extend this is in `scripts/claude_sdk_harness/`
and every raw run is under `.ab_workspaces/claude_sdk_harness/<run>/`
(`arm_without.json`, `arm_with.json`, `report.json`, `warm_proof.json`).
