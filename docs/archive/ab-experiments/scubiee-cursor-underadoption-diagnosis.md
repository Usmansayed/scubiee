# Why Scubiee doesn't help Cursor on the complex task — root-cause diagnosis

Traced from the actual Cursor decision traces of the `cli_health_command` with/without run
(`cell_k_2cfg_r1.trace.md` / `.trace.json`) plus reproduced map queries against the 2cfg bridge.
This replaces the earlier hand-wavy "Cursor under-adopts" with the concrete mechanism.

## What actually happened (k_2cfg r1, Cursor)
The agent made **54 tool calls** but only **1 map call** (`scub=1`, `cfg={'find':1}`), then grep/read
for the rest. Sequence:
1. Actions 1-14: the Cursor `auto` model opened by deciding "the requested change is NOT in the
   message" and spent ~14 glob/grep/read calls hunting the workspace (even reading `.cursor/projects`
   and the harness source) to reconstruct the task. **NOTE: the task prompt WAS delivered** — the
   feature text ("is Scubiee healthy", "one-word verdict") is present in the trace.json. This was the
   model misreading its own initial context, not a harness bug. It inflated BOTH arms' tokens.
2. Action 15: it finally called map ONCE with a COMPOUND query — asking for TWO unrelated things at
   once: (a) "CLI subcommand registration in __main__.py add_parser set_defaults cmd_status" AND
   (b) "build_sync_contract sync_status ... health verdict".
3. The find result returned only (b) — `build_sync_contract` (3 results, high confidence) — and
   **completely missed (a)**: no `__main__.py`, no `add_parser`, no `cmd_status`.
4. The agent's reasoning: "the CLI registration was missing from the map results. I will grep
   __main__.py directly." From there it never meaningfully returned to map — it grep-walked.

## Root cause (reproduced, not guessed)
Re-running the agent's exact query against the 2cfg bridge confirms it:
- The COMPOUND find returned `sync_status.py::build_sync_contract` only; `__main__.py` / add_parser /
  cmd_status = **absent**. The semantic ranker latched onto the single strongest semantic cluster and
  the default `k` truncated the weaker, lexical/structural CLI-registration target off the list.
- But the info WAS retrievable with the right call:
  - `focus names=["cmd_status"]` → returned **`__main__.py::cmd_status` lines 805-876 exactly** — the
    precise code the agent needed.
  - a NARROW single-target `find` ("how CLI subcommands are registered: add_parser set_defaults") →
    surfaced `__main__.py` as result #2.

So the tool could have served the agent. **The failure was query STRATEGY, and the strategy was
shaped by the rule.**

## Three contributing factors (ranked)
1. **Compound single-query habit (primary).** The k_2cfg rule says "one semantic query" and
   "a BROAD find query to orient." On a task with TWO distinct targets (registration site + status
   contract) that advice backfires: a broad compound query retrieves only the dominant cluster and
   silently drops the other target. One miss → the agent distrusts map → reverts to grep for the rest.
2. **find under-retrieves structural/lexical targets.** CLI registration (`add_parser`, `cmd_status`
   in `__main__.py`) is a STRUCTURAL pattern, not a semantic concept, so semantic `find` ranks it
   below a strong semantic match and `k` cuts it. `focus` on the name nails it — but the rule didn't
   push the agent to `focus` the known names here (it led with find).
3. **Cursor `auto`'s native-exploration default + the "task not in message" misread** front-loaded
   ~14 native calls before map ever ran, setting a grep-walk momentum that one mediocre map result
   didn't overcome. (Kiro did NOT do this — it mapped early and trusted the results, hence 6-12 map
   calls and the ~2.8x win.)

## Why Kiro didn't hit this
Same rule, same tool. Kiro's agent mapped EARLY and issued MULTIPLE targeted calls (find+focus,
e.g. `{'find':6,'focus':6}`) instead of one compound query, so each call got a clean, trustworthy
result and map substituted for native search. Cursor's `auto` issued one compound query, got a
half-answer, and bailed to grep. **Adoption is behavioral, and the behavioral trigger here is
query decomposition, not the config count.**

## Fix hypotheses (to test next)
A. **Rule change: "one target per query; split multi-target work into separate find/focus calls;
   when you know a name, `focus` it — do NOT bundle a structural lookup into a semantic query."**
   This directly attacks factor #1 and #2. Expected: Cursor issues 2-3 targeted calls, each lands,
   trust holds, grep-walk shrinks.
B. **Rule change: lead with focus for known names.** The agent already KNEW `cmd_status`/`cmd_X` and
   `build_sync_contract` — a `focus names=[...]` first move would have returned both bodies+wiring in
   one or two clean calls. Add an explicit "known name → focus FIRST" worked example to k_2cfg.
C. **Tool change (optional): raise find's `k` / add a lexical fallback so a compound query still
   surfaces a structural target.** Riskier (bigger results = more tokens); prefer the rule fixes
   first since the tool CAN serve the right calls today.

## Bottom line
Cursor's complex-task under-adoption is NOT a 2-config problem and NOT a harness bug. It's: a
compound find query that under-retrieved one of two targets, which broke map's trust and reverted a
grep-happy `auto` agent to native search. The tool had the answer via `focus`/narrow-find. The lever
is a query-decomposition rule (fix A/B), not the config count — confirmed by Kiro succeeding with the
identical tool+rule by decomposing its queries.
