# 3-config map vs old map (v3): arm test after heavy preflight

Second live arm test, now with the map collapsed to 3 configs and the configs rules rewritten with a worked example per config. Gated behind five preflight checks, all green, before any tokens.

| Arm | Tools | Rules |
|---|---|---|
| `mini_v3` | old simple map (one `find`-style tool) | v3 strict |
| `newmap` | 3-config map (`find/refs/view`) | configs rules (284 + 1383 tokens) |

Clean conditions: no Bash, no self-testing, full-repo snapshot. Both arms edit; the hidden oracle grades behavior. n=1 per cell.

## Preflight (all green, zero arm tokens)

1. Compile + token check (rules 284, instructions 1383, both under cap)
2. Offline battery `test_map_v2.py` — 24/24
3. SDK-spawn preflight `preflight_map_v2.py` — 11/11, config enum = find/refs/view
4. Old-map bridge spawns and returns a usable map; both rule sets load
5. Dev-runner preflight (static + warm + snapshot) for `mini_v3,newmap` on both tasks
6. Live Claude probe on the 3-config bridge — a real Sonnet agent called find/refs/view (both refs modes, both view modes), 0 trace errors, all usable (88k tokens)

## Results

| Task | Arm | tokens | calls | map calls | grep | oracle | pass |
|---|---|---:|---:|---:|---:|---:|:--:|
| cache_aware_savings (multi-module) | mini_v3 | **400,364** | 11 | 1 | 0 | 1.0 | yes |
| cache_aware_savings | newmap | 692,488 | 17 | 5 | 0 | 1.0 | yes |
| dirty_files_cap (keyword, 1 file) | mini_v3 | **249,463** | 8 | 1 | 2 | 1.0 | yes |
| dirty_files_cap | newmap | 254,872 | 8 | 4 | 1 | 1.0 | yes |

Both arms passed both tasks (4/4). mini_v3 was cheaper on both.

## What changed vs the 5-config run, and what didn't

**The keyword task improved a lot.** In the 5-config run newmap cost 353k on dirty_files_cap (5 map calls, over-exploring with around + 3 refs). Now it's **255k, essentially tied with old map's 249k** — same 8 calls. The 3-config surface + the "edit after find, don't look around" rule cut the over-exploration on the easy task to near-zero.

**The hard task still over-explores.** On cache_aware_savings, newmap made **5 map calls (692k)** vs mini_v3's 1 (400k). The sequence: `find` (returned the body) -> `view` outline -> `refs` [compare_queries, ArmResult, QueryCompare] -> `refs` [compare_queries] -> `view`. The agent used the configs to map the whole module before editing.

Two honest readings of that:
- It is partly legitimate: this task's correct fix touches a dataclass plus two functions plus the comparison, so understanding the wiring is real work. newmap passed; in the 5-config run on this task mini_v3 had *failed* it.
- But it is still more calls than needed. `find` returned the target function; the extra `view`+`refs`+`view` were the agent building confidence, not strictly required to make the edit.

**Payload is not the problem.** newmap pulled only 17,226 result-chars on the hard task and ~10k on the easy one. The extra tokens are entirely round-trips (each re-reading the transcript), which is the known cost lever.

## Honest standing

- **Correctness: 4/4 for both arms this round.** The 3-config map is reliable.
- **Cost: old map (v3) is cheaper at n=1 on both tasks.** The new map is tied on the keyword task and ~1.7x on the multi-module task, entirely due to extra map calls, not bigger results.
- **The remaining gap is behavioral, not structural.** Collapsing to 3 configs fixed the easy-task over-exploration; the hard-task case is the agent choosing to build a module model with cheap config calls. The rules say "act on the first good answer," but with low-cost configs the agent still explores.

## What this points to

The new map clearly gives the agent better, cheaper *per-call* information (tiny result-chars, grep-free), and it's correct. It is not yet a token win because the agent makes more calls, and at n=1 the per-call tax outweighs it on these two tasks. Options, in order of value:
1. **n>=3 per cell.** n=1 is noisy; mini_v3 itself swung 400k-998k on this task across earlier runs. The real comparison needs repeats before concluding old map is cheaper.
2. **A harder, genuinely multi-file task** where mini_v3's single-map approach fails or grep-walks (as it did in the 5-config run), so the new map's extra calls buy correctness the old map can't get.
3. **Tighten the rule further**: cap exploratory calls — after `find` returns a confident body, allow at most one more locate call (a `refs` or `view`) before an edit, matching the "stop and edit" intent.

I did not change the rules again this round. The data says: the 3-config map is correct and leaner per call, over-exploration is down on easy tasks and remains on the hard one, and whether it wins on cost needs n>=3 and a task where correctness separates the arms.

## Files
- Runner: `run_dev_mini.py` (arms mini_v3, newmap) · Map: `map_v2_bridge.py` (3 configs)
- Rules: `policies.RULES['configs']` · Gates: `test_map_v2.py`, `preflight_map_v2.py`, `probe_map_v2_live.py`
- Run dirs: latest `*_devmini_cache_aware_savings`, `*_devmini_dirty_files_cap`
