# New map (5 configs) vs old map (v3 rules): first live arm test

Two arm sets, real Claude agents, clean conditions (no Bash, no self-testing, full-repo snapshot). Both arms edit code; the hidden oracle grades the behavior.

| Arm | Tools | Rules |
|---|---|---|
| `mini_v3` | old simple map (`find`-only, one tool) | v3 strict (prior best) |
| `newmap` | 5-config map (`find/refs/open/around/outline`) | configs rules (275 + 1021 tokens) |

Gated behind proof the new tool works: 41/41 offline checks, an SDK-spawn preflight (all 5 configs usable over the exact spawn path), and a live Claude probe (a real agent called all 5 configs, 0 errors, self-reported all usable). Only then these runs.

## Results

| Task | Arm | tokens | model calls | map | grep | reads | edits | oracle | pass |
|---|---|---:|---:|---:|---:|---:|---:|---:|:--:|
| dirty_files_cap (keyword, 1 file) | mini_v3 | **258,057** | 8 | 1 | 2 | 1 | 1 | 1.0 | yes |
| dirty_files_cap | newmap | 353,116 | 11 | 5 | 2 | 1 | 1 | 1.0 | yes |
| cache_aware_savings (multi-module) | mini_v3 | **462,220** | 12 | 2 | 4 | 2 | 1 | 0.33 | **no** |
| cache_aware_savings | newmap | 544,249 | 13 | 3 | 0 | 2 | 1 | 1.0 | **yes** |

n=1 per cell, so read these as direction, not settled numbers.

## What happened in each

**dirty_files_cap (keyword-friendly, single file) — old map cheaper.**
`newmap`'s `find` nailed the file in one call (2,438 chars). But the agent then ran `around` + **three `refs` calls** before editing — it explored every config when `find` → edit was enough. config_use: find 1, around 1, refs 3. mini_v3 did find → edit in fewer calls, so it was cheaper (258k vs 353k). Both passed. The extra cost was round-trips, not payload (newmap pulled only 10,241 result chars).

**cache_aware_savings (multi-module) — new map correct, old map wrong.**
`newmap` ran the intended trajectory: `find` → `refs` → `open`, **grep=0**, edit, pass (1.0). mini_v3 found the file but its edit only satisfied 1 of 3 behavior checks (oracle 0.33, fail): on this harder task the single-map agent grepped around (4 greps) and made an incomplete change. So newmap cost ~18% more tokens but was the only arm that got the task right.

## Reading it honestly

- **Correctness, 3 of 4 passes, and newmap got the one that mattered.** On the hard task newmap passed and old map failed. That is the result that counts: a cheaper wrong answer is not cheaper.
- **On the easy task, the new tool cost more because the agent over-explored.** This is a rules gap, not a tool gap: the configs make exploration cheap, so the agent used `around` and repeated `refs` when `find` had already answered it. The "stop retrieving the moment you can edit" rule did not bite hard enough.
- **The cost difference is round-trips, not payload.** newmap's result-chars were small both times (10k, 30k). The extra tokens are the extra `refs`/`around` calls, each re-reading the transcript — exactly the lever the rules are supposed to control.
- **grep went to 0 on the hard task with newmap**, vs 4 for old map. The configs did replace the grep-walk, which was their main job.

## The fix (rules, not tool)

The over-exploration on the easy task is a one-line tightening of the configs rules: after `find` returns a confident body, if that is the place you need to edit, **edit — do not call refs/around/open to look around first**. The rules already say "stop retrieving the moment you can edit"; it needs to be a hard MUST NOT, like the anti-re-grep rule in v3, with an explicit bad example (`find` answered it, then refs/around anyway).

I did **not** change the rules yet — that is a new iteration, and I would want your go-ahead before another token spend to test it.

## Standing

- The new map **works end to end with a real agent** and, on the task that separated the arms on correctness, it was the one that passed.
- It is **not yet a clean token win**: on easy tasks the agent over-explores the configs. Fixable in the rules.
- n=1 per cell. To settle it: tighten the stop-and-edit rule, then run both tasks at n=3 (old map v3 vs new map, clean) and compare median tokens, calls, and pass rate.

## Files
- Runner: `scripts/claude_sdk_harness/run_dev_mini.py` (arms `mini_v3`, `newmap`)
- New map: `scripts/claude_sdk_harness/map_v2_bridge.py`
- Rules: `policies.RULES['configs']` (`two_layer.py` RULES_CONFIGS / INSTRUCTIONS_CONFIGS)
- Gates: `test_map_v2.py` (41/41), `preflight_map_v2.py`, `probe_map_v2_live.py`
- Run dirs: `.ab_workspaces/claude_sdk_harness/*_devmini_dirty_files_cap`, `*_devmini_cache_aware_savings` (latest two)
