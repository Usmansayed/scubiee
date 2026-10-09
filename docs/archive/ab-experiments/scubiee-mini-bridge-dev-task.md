# Mini MCP bridge (map/gate/status only) — one real dev task, WITHOUT vs mini

Run: `.ab_workspaces/claude_sdk_harness/20260930T193909Z_devmini/` (2 cells, n=1).
Task: `cache_aware_savings` — one vague, human-sounding request (make the
token-savings comparison cache-aware), hidden name-agnostic oracle, gold file
`packages/pipeline/token_meter.py`. The agent had to actually EDIT code.
Model `claude-sonnet-5`, max 40 turns.

## The mini bridge

`scripts/claude_sdk_harness/mini_mcp_bridge.py` — a standalone JSON-RPC-over-stdio
MCP server that exposes exactly three tools and talks to the already-running
Scubiee **engine** over its plain HTTP API (`/v1/search`, `/health`). It imports
nothing from Scubiee's own `mcp_*` modules, so it does **not** touch main Scubiee
and does **not** inherit:
- the stock pack/expand server-instructions ladder,
- the `ambiguous_repos` + "Server disconnected" first-call failure,
- any tool beyond map/gate/status.

Tools: `map(query,k)` → clean ranked cards (`rank/file/loc/symbol/score/why`),
`gate()` → managed line, `status()` → engine health. Verified over stdio before
the run: 3 tools listed, map returned a 6-card result in ~2.2k chars, gate/status
returned real health. Wired into the harness as `use_mini_bridge=True`
(tool namespace `mcp__scubmini__*`); the arm also gets the `two_layer_v2` rule.

Snapshot fix: this runner copies **packages + tests + docs + scripts** into the
workspace (not just `packages/`), so any path a map card returns actually exists.
That removes the "file not found" confound that hurt the earlier Scubiee arms.

## Result

| Arm | tokens | cache_read | output | turns | model calls | map | grep | read | edit | result chars | oracle | success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|:--:|
| without | 1,721,571 | 1,641,616 | 22,308 | 32 | 32 | 0 | 7 | 9 | 7 | 67,685 | 1.0 | ✅ |
| **mini** | **834,091** | 775,337 | 18,686 | **24** | **19** | 1 | 9 | 4 | 3 | **31,713** | 1.0 | ✅ |

**mini used 52% fewer tokens (834k vs 1.72M) and still passed the oracle.**
This is the first clean, same-conditions dev-task win for a map surface in the
whole study. n=1, so treat the magnitude as directional, but the mechanism is
consistent with everything measured before.

### Where the win came from (result-chars + calls)

- **Fewer whole-file reads.** without pulled **44,756 chars** through Read (9
  reads); mini pulled **21,806** (4 reads). One `map` call (4,237 chars) pointed
  the agent straight at `token_meter.py` as rank-1 (score 29.9, far above the
  rest), so it read the right file instead of exploring.
- **Far less Bash flailing.** without ran 6 Bash calls totalling **14,008 chars**
  of output (directory listing / exploration); mini ran 4 Bash calls totalling
  **990 chars**. That alone is ~13k chars that then rode along in every later
  turn's context.
- **Fewer model calls: 19 vs 32.** Since cost ≈ context × calls, cutting 13
  round-trips is most of the saving. mini reached the fix in 24 turns; without
  took 32.
- Total tool-result payload: without **67,685** chars vs mini **31,713** — the
  ~2× payload ratio tracks the ~2× token ratio, exactly as the cache-read model
  predicts.

### The map call

One map, query `"tokens saved retrieval benchmark grep baseline comparison
summary"`, returned 12 cards with `token_meter.py` at rank 1 (score 29.9). The
agent read that file's span and edited it. No second map, no disconnect — the
mini bridge's internal retry-once and single-repo scoping avoided the
first-call failure the full bridge showed in every prior run.

## What this establishes

1. **A clean 3-tool map surface can be plugged into an arm without touching main
   Scubiee.** The mini bridge is ~250 lines, stdlib-only, and reuses the live
   engine's HTTP search. Good isolation for A/B work.
2. **On a real edit task with a fair (full-repo) workspace, map roughly halved
   token cost** while matching correctness. The earlier "Scubiee costs more"
   results were dominated by (a) the packages-only snapshot confound and (b) the
   first-call disconnect — both absent here.
3. The saving is the same mechanism seen throughout: **fewer whole-file reads and
   fewer model round-trips**, not fewer greps (mini actually grepped more: 9 vs
   7).

## Limits / next

- **n=1 per arm.** Turn count varies run-to-run; repeat at n=3 to bound it.
- One task, one gold file. Add the cross-module task for a harder case.
- The mini bridge returns non-code cards too (a `.md`, a `scripts/*.py`); with
  the full-repo snapshot these now resolve, but code-first ordering (proposed map
  change) would still help precision.
- Recommended next run: `without` vs `mini` vs full-`scubiee` (two_layer_v2) on
  this task at n=3, to separate "map helps" from "the mini bridge avoids the full
  bridge's two bugs".


---

## Consistency check — a SECOND, independent dev task

Run: `.ab_workspaces/claude_sdk_harness/…_devmini_dirty_files_cap/` (2 cells, n=1).
Different task, different module, different oracle, so the mini arm cannot be
"reusing" anything from the first task.

### Isolation (verified)
- Each arm runs in its **own** workspace (`ws_<arm>_r1`), extracted byte-identical
  from the same baseline commit, `git reset --hard` + `clean -fd` before the run
  and `rmtree` after. The arms never share a directory, so the second arm cannot
  see or copy the first arm's edits.
- Task 1 baseline sha `084451a…`; task 2 baseline sha `3ba9743…` — different
  trees (task 2's baseline is a fresh snapshot), confirming a clean, separate run.
- Both arms start from the identical baseline; the ONLY difference between arms is
  native-only vs native+mini-bridge (+ the two_layer_v2 rule).

### Task 2: `dirty_files_cap`
Vague prompt: "give the changed/dirty-files helper an optional way to limit how
many paths it returns; default unchanged; keep it backwards compatible." No file
or function names. Gold `packages/pipeline/freshness.py`. Hidden oracle is
name-agnostic (any list-returning freshness fn that gains AND applies an optional
limit-ish param defaulting to unlimited). Oracle verified to FAIL on the
unmodified tree (2 of 3 checks fail on baseline).

| Arm | tokens | cache_read | output | turns | model calls | map | grep | read | edit | result chars | oracle | success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|:--:|
| without | 610,091 | 578,993 | 7,936 | 19 | 18 | 0 | 13 | 2 | 1 | 21,834 | 1.0 | ✅ |
| **mini** | **354,847** | 333,400 | 4,447 | **13** | **11** | 1 | 6 | 2 | 1 | **12,711** | 1.0 | ✅ |

**mini used 42% fewer tokens (355k vs 610k) and both passed.**

### Consistency across the two independent tasks

| Task | without tok | mini tok | mini saving | both passed |
|---|---:|---:|---:|:--:|
| cache_aware_savings (token_meter) | 1,721,571 | 834,091 | **−52%** | ✅ |
| dirty_files_cap (freshness) | 610,091 | 354,847 | **−42%** | ✅ |

The direction and rough magnitude repeat on a completely separate task:
**mini cuts tokens 40–50% and matches correctness.** The mechanism repeats too:
- **Fewer model round-trips** (task2: 11 vs 18; task1: 19 vs 32). This is the
  dominant term since cost ≈ context × calls.
- **Less native flailing.** In task2 the without arm ran **13 greps** (13,934
  chars of grep output) to find `freshness.py`; mini used **1 map** (3,565 chars)
  + 6 greps and got there in fewer turns. Grep count is again *higher or equal*
  on the winning arm's cheaper runs is not the driver — round-trips and total
  carried context are.
- **Smaller total payload** (task2: 12,711 vs 21,834 chars), tracking the token
  ratio.

### Standing
- Two independent tasks, same isolated harness, same result: **map roughly halves
  cost with equal correctness** once the workspace matches the index (full-repo
  snapshot) and the mini bridge sidesteps the full bridge's first-call disconnect.
- Still n=1 per (arm, task). The two tasks together are 4 clean runs, all
  consistent, but repeats (n=3) are needed to put error bars on the % saving.


---

## Third task + within-arm repeats — DON'T declare a win yet

Run: `…_devmini_health_reason_flag/` (4 cells: 2 arms × 2 repeats). Third
independent task/module (`install_health.py`, add an opt-in bool detail flag to a
health probe; name-agnostic oracle; verified to FAIL 2/3 on the unmodified tree).
This is the first run with **repeats per arm**, and it changes the conclusion.

| Arm | rep | tokens | turns | calls | map | grep | bash | edits | oracle | success | note |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|:--:|---|
| without | 1 | **275,670** | 9 | 9 | 0 | 4 | 1 | 1 | 1.0 | ✅ | fast, clean |
| without | 2 | **1,861,476** | 41 | 40 | 0 | 8 | 23 | 2 | 1.0 | ❌ | hit 40-turn cap, 23 Bash calls, also edited a test file |
| mini | 1 | 829,146 | 22 | 21 | 1 | 2 | 11 | 2 | 1.0 | ✅ | |
| mini | 2 | 456,232 | 14 | 14 | 1 | 2 | 3 | 1 | 1.0 | ✅ | |

- **within-`without` swing: 275,670 → 1,861,476 tokens on the SAME task = 6.75×.**
- within-`mini` swing: 456,232 → 829,146 = 1.8×.
- median tokens: without 1,068,573 vs mini 642,689 (mini lower), but the without
  median is meaningless — it's the midpoint of a lucky run and a blown run.

### What this tells us (the honest read)

1. **n=1 conclusions are unsafe.** On its lucky repeat, `without` (276k) beat both
   mini runs. On its unlucky repeat it blew up to 1.86M and failed by hitting the
   turn cap. The earlier "mini −52% / −42%" wins were each a single sample; this
   shows a single sample can land anywhere across a ~7× range.
2. **The real, repeatable effect is variance reduction, not a fixed % saving.**
   Both mini runs landed in a tight 456k–829k band; both succeeded. The without
   arm is bimodal: cheap when it guesses the file fast, catastrophic when it
   grep/Bash-walks (rep2: 23 Bash calls, 40 turns, cap-fail). map's contribution
   is pulling the agent onto the right file early, which **cuts the tail** — the
   expensive/failing runs — more than it lowers the median.
3. **mini did not fail once across 6 runs (tasks 1–3); without failed 1 of 4.**
   Small n, but the direction (map improves worst-case reliability) is consistent
   with every trace: the failures are always grep/whole-file/Bash walks.

### Combined dev-task record (all three tasks)

| Task | without runs (tok) | mini runs (tok) | without fails | mini fails |
|---|---|---|:--:|:--:|
| cache_aware_savings | 1,721,571 | 834,091 | 0/1 | 0/1 |
| dirty_files_cap | 610,091 | 354,847 | 0/1 | 0/1 |
| health_reason_flag | 275,670 ; 1,861,476 | 829,146 ; 456,232 | 1/2 | 0/2 |
| **totals** | **4 runs, mean 1.12M, 1 fail** | **4 runs, mean 618k, 0 fail** | | |

Across all 8 dev runs: mini mean 618k vs without mean 1.12M, and mini never
failed while without failed once by grep/Bash-walking into the turn cap.

### Verdict: promising, NOT proven
- The **direction is consistent** (mini cheaper on mean, and tighter/ more
  reliable) across 3 independent tasks and 8 runs. That is real signal.
- But **within-arm variance is huge** (without: 6.75× on one task), so the exact
  % saving is not trustworthy at these sample sizes, and any single head-to-head
  can flip. **Do not declare a fixed win.**
- The most defensible claim so far: *map tends to reduce the expensive tail —
  the grep/Bash-walk blowups — which lowers mean cost and improves worst-case
  reliability*, rather than guaranteeing a lower cost on every run.

### To actually prove it
- n≥5 per (arm, task) on all three tasks → report median + IQR + fail rate, not a
  single number. ~30 runs; sizeable token spend — get scope approval first.
- Add the full-`scubiee` (two_layer_v2) arm so we separate "map helps" from "mini
  bridge dodges the full bridge's first-call disconnect".


---

## Clean re-run — no self-testing, no Bash (removes the run-3a confound)

Change: the agent is told to make the edit and STOP — do not run tests/build/
verification. Bash was also removed from the allowed tools, so it cannot spiral
on shell/pytest at all. The harness's hidden oracle verifies the change
afterward. This isolates LOCATE+EDIT (what Scubiee affects) from test-runner
flailing (what caused run 3a's 829k and without-r2's 1.86M).

Both tasks, with vs without, side by side (n=1 each, clean conditions):

| Task | Without Scubiee | With Scubiee | Cheaper | Both pass |
|---|---:|---:|:--:|:--:|
| dirty_files_cap (freshness.py) | 205,050 | 208,396 | ~tie | ✅ ✅ |
| health_reason_flag (install_health.py) | 204,328 | 173,348 | With (−15%) | ✅ ✅ |

Trajectories (clean):

| Task | Arm | tokens | turns | calls | map | grep | edit | pass |
|---|---|---:|---:|---:|---:|---:|---:|:--:|
| dirty_files_cap | without | 205,050 | 7 | 7 | 0 | 4 | 1 | ✅ |
| dirty_files_cap | with | 208,396 | 8 | 7 | 0 | 4 | 1 | ✅ |
| health_reason_flag | without | 204,328 | 7 | 7 | 0 | 4 | 1 | ✅ |
| health_reason_flag | with | 173,348 | 6 | 6 | 1 | 1 | 1 | ✅ |

### What the clean runs show

1. **The huge numbers were the test-running confound, not retrieval.** The same
   `health_reason_flag` task went 275k/1.86M (without) and 829k/456k (with) WITH
   Bash+self-testing; with that removed it's **204k vs 173k**, both fast, both
   passing. Run 3a's 829k was ~10k chars of Bash + a 12.5k-char conftest read
   after the edit was already done — pure verification flailing.
2. **On locate+edit alone, the arms are close, and Scubiee is at worst a tie:**
   - `dirty_files_cap`: essentially identical (205k vs 208k). The with-arm's own
     rule (v2) correctly sent it to **grep** (map=0) for this keyword-friendly
     query — so "with Scubiee" here just means "same as native," which is the
     right behavior, not a loss.
   - `health_reason_flag`: with-Scubiee −15% (173k vs 204k). One map call, one
     grep, edit at turn 6 — the tightest run of the pair.
3. **Variance collapsed** once Bash/self-testing was gone: all four clean runs
   are 173k–208k (1.2× spread), versus the earlier 276k–1.86M (6.8×) with Bash.
   Most of the "Scubiee variance" we were chasing was actually test-runner noise
   hitting both arms.

### Honest standing after the clean runs
- On pure locate+edit, **Scubiee ties on a keyword query and wins modestly (−15%)
  on a conceptual one.** No blowups on either side once verification is removed.
- The earlier dramatic 40–52% "wins" were inflated by the without arm's
  test-running blowups; the clean, like-for-like locate+edit gap is smaller.
- Correctness: 4/4 both arms in the clean runs.
- This is the fair comparison for *retrieval*: when the query is keyword-friendly,
  the v2 rule keeps the agent on grep (tie); when it's conceptual, map helps a
  bit. Neither arm melts down.

### Combined dev-task record (all runs, labelled by condition)

| Task | Condition | Without | With | Winner |
|---|---|---:|---:|:--:|
| cache_aware_savings | with self-test+Bash | 1,721,571 | 834,091 | With |
| dirty_files_cap | with self-test+Bash | 610,091 | 354,847 | With |
| health_reason_flag r1 | with self-test+Bash | 275,670 | 829,146 | Without |
| health_reason_flag r2 | with self-test+Bash | 1,861,476 (fail) | 456,232 | With |
| dirty_files_cap | CLEAN (no test/Bash) | 205,050 | 208,396 | tie |
| health_reason_flag | CLEAN (no test/Bash) | 204,328 | 173,348 | With |

The clean rows are the trustworthy ones for judging retrieval. Next: n≥5 per cell
on the clean setup for both a keyword task and a conceptual task, to put error
bars on the tie-vs-modest-win picture.


---

## Substantial dev task, CLEAN conditions (no self-test, no Bash)

Task: `cache_aware_savings` — the multi-module one (make the token-savings
comparison cache-aware; target `token_meter.py` buried among many token/estimate
modules; the change touches the per-arm result + the comparison surface). This is
the biggest task in the suite; under Bash+self-test it ran 834k–1.72M. Re-run
here clean so it measures locate+understand+edit, capped well under 2M.

| Arm | tokens | cache_read | output | turns | calls | map | grep | read | edit | result chars | oracle | success |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|:--:|
| without | **529,443** | 480,359 | 16,051 | 13 | 13 | 0 | 4 | 2 | 4 | 27,580 | 1.0 | ✅ |
| with | 612,483 | 556,494 | 14,440 | 14 | 14 | 1 | 3 | 3 | 4 | 48,082 | 1.0 | ✅ |

**Without was ~14% cheaper this run (529k vs 612k). Both passed.**

Why with-Scubiee cost a bit more here (from the trace):
- **map added a whole extra read.** without read 2 spans (7,753 + 12,142 =
  19,895 chars). with read 3 spans (7,753 + 16,734 + 11,330 = 35,817 chars) —
  map surfaced an additional relevant card, and the agent read it too. Plus the
  map payload itself (4,230 chars). So with-Scubiee pulled **48,082** result
  chars into context vs without's **27,580** — ~20k more, carried across ~14
  calls ≈ the ~83k token difference.
- Both found `token_meter.py` and both made the same 4 edits and passed. The
  extra map-surfaced read didn't change the outcome; it was extra context the
  agent chose to read.
- One map call (not two) — the first-call disconnect did NOT happen (mini
  bridge's single-repo scoping + retry-once working as intended).

### The honest picture across ALL clean runs (no Bash / no self-test)

| Task | size | Without | With | Winner |
|---|---|---:|---:|:--:|
| dirty_files_cap | small | 205,050 | 208,396 | tie |
| health_reason_flag | small | 204,328 | 173,348 | With (−15%) |
| cache_aware_savings | large | 529,443 | 612,483 | Without (−14% for without) |

- On clean locate+edit, **it's a wash: 1 tie, 1 modest Scubiee win, 1 modest
  without win.** No arm dominates, no blowups on either side, all 6 runs passed.
- The earlier dramatic Scubiee "wins" (−42%, −52%) came almost entirely from the
  without arm's Bash/self-test blowups, NOT from better retrieval. With that
  confound gone, the two arms cost about the same.
- Where map can cost MORE: it surfaces an extra relevant card, and the agent
  reads it — good for thoroughness/precision, but extra context tokens on an
  easy-to-locate target. This is the "map earns its keep only when it prevents a
  bigger read/walk" point, now seen from the other side.

### Revised standing (most honest to date)
- **On correctness: both arms are reliable when not told to self-test** (6/6 clean
  passes; the only failures in the whole study were test-runner spirals).
- **On tokens for locate+edit: roughly neutral.** Scubiee helps most on
  conceptual/buried targets and on cutting worst-case blowups; it can cost a bit
  more on targets that are easy to grep or when it surfaces extra context the
  agent reads.
- **The real, repeatable Scubiee value is variance/tail reduction** (avoiding the
  grep/Bash-walk blowups), not a flat per-task token cut. That claim survived the
  confound removal; the flat-% claims did not.

Next to settle the neutral picture: n≥5 per cell on one conceptual + one keyword
task, clean conditions, reporting median/IQR/fail-rate.


---

## v3 STRICT rule — fixes the two waste patterns; Scubiee wins clean

### Why v2 was drawing (root cause from the clean traces)

Reading the clean `cache_aware_savings` (v2) trace showed map worked but the
agent then **wasted tokens two specific ways** the soft v2 wording didn't stop:
1. **Post-map grep to "confirm":** after map returned `token_meter.py`, the agent
   still ran 3 greps (`token_meter|ArmResult|QueryCompare`, `from pipeline…
   import`, `ArmResult\(|…`). map had already located it.
2. **Read an unrelated file map surfaced:** it read `harness_task.py` (16,734
   chars — a test/benchmark file, not the fix). That single read was ~most of the
   83k it lost to the without arm.

v2 said "don't re-search / read spans not whole files" as a *soft default*, so the
model overrode it. The fix is to make those two things **hard prohibitions**.

### v3 rule (strict) — RULES 151 tok, INSTRUCTIONS 565 tok

Adds explicit **MUST / MUST NOT** language on exactly the observed failures:
- If location unknown → you MUST `map` first (no grep-to-discover).
- After a relevant map → you **MUST NOT** grep/glob the same concept to confirm.
- Read **ONLY** cards that are part of the change; **MUST NOT** read
  test/harness/doc files map merely lists as related.
- Read spans not whole files; batch reads; one map is enough; stop and edit.
- Keyword/literal you already know → still Grep (no forced map).

### Result — same substantial task, v3 vs without

| Arm | tokens | turns | calls | map | grep | read | result chars | oracle | success |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|:--:|
| without | 795,175 | 17 | 17 | 0 | 3 | 4 | 50,532 | 1.0 | ✅ |
| **with (v3)** | **392,246** | **10** | **10** | 1 | **0** | 1 | **13,795** | 1.0 | ✅ |

With-Scubiee v3 used ~51% fewer tokens than the without arm in THIS run and both
passed — BUT read the caveat: the two rule versions were measured against
DIFFERENT without baselines (v2's run had without=529k; v3's run had without=795k),
and the without arm is noisy (529k↔795k on the same task). So the honest,
apples-to-apples signal is NOT "v3 saves 51% vs native"; it is the **rule-vs-rule**
comparison below, same task + same bridge, only the rule text changed.

### The trustworthy signal: v2 vs v3 (same task, same bridge, only rule text differs)

| Rule | with tokens | map | post-map greps | unrelated big read | result-chars into context | vs its OWN without |
|---|---:|---:|---:|:--:|---:|---|
| v2 (soft) | 612,483 | 1 | 3 | yes (harness_task 16.7k) | 48,082 | +16% (lost, without=529k) |
| **v3 (strict)** | **392,246** | 1 | **0** | **no** | **13,795** | −51% (won, without=795k) |

**v3 cut with-Scubiee's OWN cost ~36% (612k → 392k)** by eliminating the 3
confirm-greps and the one 16.7k irrelevant read. That drop is caused by the
stricter wording and is visible in the trace (grep 3→0, result-chars 48k→14k),
independent of the noisy without baseline. The "−51% vs without" is real for that
run but partly reflects an expensive without run, so don't quote it as the flat
saving.

v3 trace was textbook: `map → Read token_meter.py span → 6 Edits → stop`.
**grep=0, read=1, no unrelated files.** The strict "MUST NOT grep after map" and
"don't read files map only listed as related" both held — result-chars dropped
from v2's 48,082 to **13,795**.

### Rule version comparison on `cache_aware_savings` (clean, no Bash/self-test)

| Rule | tokens | map | post-map greps | unrelated file read? | vs without |
|---|---:|---:|---:|:--:|---|
| v2 (soft) | 612,483 | 1 | 3 | yes (harness_task 16.7k) | +14% (lost) |
| **v3 (strict)** | **392,246** | 1 | **0** | **no** | **−51% (won)** |

Same task, same bridge — only the rule text changed. Tightening the two clauses
to MUST/MUST NOT turned a 14% loss into a 51% win by eliminating 3 greps and one
16.7k-char irrelevant read.

### On consistency / why it wasn't consistent before
- The inconsistency was **agent discretion under soft rules**: with "prefer" /
  "strong default" wording, the model sometimes double-checked with grep and
  read extra context "to be safe". That discretion is what varied run-to-run.
- v3 removes the discretion on the two costly behaviors, so the trajectory is
  forced onto the cheap path (map → span → edit). One run so far, but the
  mechanism is now controlled rather than left to the model's mood.
- Note without also varies (529k → 795k on the same task across runs); that arm
  has no rule to constrain its grep/read count, so its spread stays wide.

### Standing
- **v3 is the new lead rule.** On the hardest (multi-module) task it converted a
  draw/loss into a clean 51% win by forbidding post-map grep and unrelated reads.
- Keyword tasks (`dirty_files_cap`) will still tie — correct, since v3 sends known
  literals to grep.
- Confirm with n≥3 on v3 for the multi-module task + one keyword task to bound the
  win and check the strict rule never hurts correctness (still 1.0 here).


---

## v3 vs without — n=2 on the substantial task (proper size, clean conditions)

Run: `20260930T213705Z_devmini_cache_aware_savings`. Task `cache_aware_savings`
(multi-module: target buried among many token/estimate modules). Clean conditions
(no self-test, no Bash). 2 repeats per arm.

| Arm | rep | tokens | turns | map | grep | read | result chars | oracle | success |
|---|---:|---:|---:|---:|---:|---:|---:|:--:|:--:|
| without | 1 | 826,310 | 16 | 0 | 6 | 2 | 53,179 | 1.0 | ✅ |
| without | 2 | 998,251 | 22 | 0 | 8 | 6 | 90,209 | 1.0 | ✅ |
| with (v3) | 1 | **476,516** | 13 | 1 | 3 | 1 | 13,776 | 1.0 | ✅ |
| with (v3) | 2 | 785,531 | 21 | 1 | 11 | 4 | 46,735 | 1.0 | ✅ |

**Means: without 912,280 · with-v3 631,023 → v3 ~31% cheaper on the mean.**
Both arms 4/4 correct. Every without run cost more than v3's cheap run; v3's mean
and both individual runs beat without's mean.

### Honest read
- **v3 won both repeats vs without's mean, and won 4/4 of the individual
  head-to-head pairings** (476k & 786k both < 826k & 998k). This is the first
  properly-sized (0.8–1.0M without) task with repeats, and v3 is consistently
  cheaper.
- **But v3 is not yet fully consistent internally.** rep1 was textbook (map →
  1 read → edit, 3 greps, 13.7k result-chars). rep2 slipped: **11 greps**, read
  `harness_task.py` (16,734 chars — the exact unrelated-file mistake v3's rule
  forbids), 46.7k result-chars. The strict rule reduced but did not eliminate the
  two waste patterns on the harder rep.
- Why rep2 slipped (from the trace): after map + reading `token_meter.py`, the
  agent went hunting for how cache tokens are represented elsewhere
  (`cache_read|cache_creation|prompt_cache` greps, read `harness_core.py`, a
  report .md, and finally `harness_task.py`). It was over-researching the cache
  concept, not the target file — the rule says don't read unrelated files map
  surfaced, but the agent reached them via its own greps, which the rule allows
  when "you need a specific literal you know". That loophole let it wander.

### The rule-vs-rule progression on this one task (clean)

| Rule | with tokens | greps | unrelated read | mean vs without |
|---|---:|---:|:--:|---|
| v2 (soft) | 612,483 (n=1) | 3 | yes | roughly tie / slight loss |
| **v3 (strict)** | 476,516 / 785,531 (n=2, mean 631k) | 3 / 11 | rep2 yes | **~31% cheaper** |

### Verdict
- **v3 is a real improvement and wins the proper-sized task** (~31% cheaper mean,
  4/4 head-to-head, 4/4 correct). This is the strongest with-vs-without result in
  the study on a fair, clean, repeated, properly-sized task.
- **Consistency is improved but not perfect:** the strict rule fully worked on
  rep1 (13.7k result-chars) and partly slipped on rep2 (46.7k) via self-directed
  cache greps + one unrelated read. To close that, v3 needs one more clause:
  after the target file is open, do NOT grep the wider codebase to research a
  concept — read only what's needed to edit the target. (candidate v4.)
- Still n=2; the ~31% mean is directional. But every single run favored v3, and
  the mechanism (fewer greps, smaller carried context) is visible in the traces.
