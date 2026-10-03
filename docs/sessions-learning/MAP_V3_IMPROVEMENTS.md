# map_v3 improvement study — cutting API calls and tokens

A cell-by-cell study of the map_v3 sessions (and the broader 124-cell dataset) to find concrete
ways to reduce API calls and save tokens. Analysis only; no Claude-token spend. Sources:
`data/sessions.jsonl`, the raw retrieval cells, `CALL_PURPOSES.md`.

---

## 1. The map_v3 cells, one by one

| task | tokens | API calls | map calls | sequence | recall | prec |
|---|--:|--:|--:|---|--:|--:|
| dirty_path_first_char | 154,522 | 5 | 2 | `find -> focus -> Write` | 1.0 | 1.0 |
| faiss_reimport_segfault | 154,364 | 5 | 1 | `find -> Read -> Write` | 1.0 | 0.33 |
| idle_engine_self_retire | **219,510** | **7** | **4** | `find -> focus -> focus -> focus -> Write` | 1.0 | 0.33 |

The two cheap cells settled in ONE map + one step. The expensive cell cost 65k more and 2 extra
calls for ONE reason: it made **three separate `focus` calls, one per symbol**.

---

## 2. Root cause #1 (biggest): `focus` is one-symbol-at-a-time

The idle_engine trace:
```
find  query="engine self-shutdown when idle..."
focus anchor="server.py::_retire_self"
focus names=["is_context_engine_process"]      <- separate call
focus names=["safe_terminate_pid"]             <- separate call
Write
```
The task touches 3 symbols across 2 files (`server.py::_retire_self`, and
`process_control.py::{is_context_engine_process, safe_terminate_pid}`). `focus` accepts a single
anchor, so the agent was FORCED into one call per symbol. Two of those symbols are in the SAME file
and still cost two calls.

This is the dataset's #1 waste pattern confirmed at the tool level: `locate_wire -> locate_wire`
(79x) and `read_body -> read_body` (19x) are exactly "call the locate/body tool again for the next
symbol".

**Fix A1 (highest ROI): make `focus` accept MULTIPLE anchors/names in one call.**
`focus names=["a","b","c"]` or `anchors=[...]` -> return each symbol's body + wiring + siblings, in
ONE response, grouping by file. The idle_engine cell collapses from 4 map calls to 2
(`find -> focus[3 names] -> Write`), ~1 fewer API call and the per-call transcript re-read saved.
Low risk: it is the same per-symbol logic in a loop, sharing the budget (the find/related configs
already pack multiple bodies this way).

**Fix A2: `find` should cluster across the FEW top files, not just the single top file.**
Today `find` packs bodies only for the one top file. idle_engine's symbols span 2 files, so `find`
could not hand over the whole set and the agent went to focus. If `find` packed bodies for the top
1-2 files when the top hits are tightly scored, the agent could edit straight from one `find` with
no focus at all. Keep a budget cap so it never dumps the repo.

---

## 3. Root cause #2: the agent re-focuses symbols `find` already returned

In idle_engine, `find` was called first and almost certainly returned `_retire_self`'s body (it is
the top hit), yet the agent still called `focus _retire_self` right after. That is a wasted call the
rules are supposed to forbid ("do NOT re-focus what find showed"). The instruction is present but did
not bind here.

**Fix B1 (rules): make find's output self-advertise its wiring so the agent trusts it.**
When `find` returns a body, append the same compact wiring line `focus` would (callers/callees), and
label it: "wiring included - do NOT focus this symbol again". The P8 lesson was that a passive note
is weak; make it part of the returned body block, adjacent to the code, not a trailing sentence.

**Fix B2 (rules): a hard per-symbol-set budget.**
Add to RULES_MAP_V3: "To gather N symbols, use ONE focus with all N names - never one focus per
symbol." Name the anti-pattern explicitly (the P3/P4 lesson: generic 'don't look around' did not stop
the specific reflex; naming the exact bad move did).

---

## 4. Root cause #3: precision drop is mostly the oracle, partly graph/related width

map_v3 precision 0.56 vs mini_v3 0.83. Reading the named-vs-gold:
- idle_engine: gold = {server.py}; map_v3 named server.py + process_control.py + daemon.py. But
  `process_control.py` holds `is_context_engine_process`/`safe_terminate_pid` - the helpers the
  self-retire logic actually CALLS. Those are genuinely part of "how it works"; the gold was just
  pinned to one commit that only touched server.py. So the "spurious" files are real neighbors.
- faiss: gold = {install_health.py}; map_v3 added incremental.py + cursor_open_preflight.py (weaker).

So ~half the precision loss is the strict single-commit oracle penalizing correct neighbors, and
~half is `graph`/`related` genuinely widening the net. For a locate-AND-EDIT goal this is fine (full
recall, you reach the target). For a "name the minimal set" goal it hurts the score.

**Fix C1 (rules, cheap): tier the answer.** Instruct: "list the PRIMARY file(s) first; put
neighbors under a separate 'related' heading." Then a minimal-set consumer reads the primary list and
a comprehension consumer gets the neighbors - without changing the tool. This recovers precision
without losing map_v3's useful breadth.
**Fix C2 (optional): `find`/`related` could mark each hit `primary|neighbor`** so the agent can
report them separately. Only if C1's rule alone doesn't hold.

---

## 5. What NOT to change (the data says these are already good)

- map_v3 already does NOT grep (0 grep across all 3 cells) and does NOT do find->read round-trips
  when find returns bodies - those leaks are designed out. Do not add grep affordances.
- Do not add more configs. The 4 are enough; the waste is WITHIN `focus` (one-per-symbol), not a
  missing config. Adding configs re-creates newmap's 3-call over-ask.
- `graph` was used ZERO times in these 3 retrieval cells (the agent went straight to find/focus).
  That's correct for "where is X" tasks - graph is for orientation in big unknown areas. Don't force
  it; just keep it available. (Watch whether it ever earns its place on a genuinely broad task.)

---

## 6. Prioritized change list (by expected token saving)

| # | Change | Where | Expected effect | Risk |
|---|---|---|---|---|
| A1 | `focus` accepts MULTIPLE names/anchors, one response grouped by file | `cfg_focus` in map_v3_bridge | collapses the #1 waste (N focus calls -> 1); idle-type cells drop ~1-2 calls / ~65k | low |
| A2 | `find` packs bodies for top 1-2 clustered files, not just 1 | `cfg_find`/map_v2 cluster logic | removes the find->focus hop on cross-file edits (-1 call) | low-med (budget cap) |
| B1 | find body block carries wiring + "do NOT focus again" inline | `cfg_find` | stops the re-focus-what-find-showed wasted call | low |
| B2 | RULES: "ONE focus with all N names, never one per symbol" | RULES_MAP_V3 | binds the agent to A1; names the exact anti-pattern | low (token budget) |
| C1 | RULES: answer lists PRIMARY first, neighbors under a heading | RULES_MAP_V3 | recovers retrieval precision without narrowing the tool | low |

Expected combined effect: the expensive multi-symbol trajectory (`find -> focus -> focus -> focus`,
220k/7 calls) collapses to `find -> focus[all] -> act` (~1 fewer call) or even `find -> act` when A2
packs the cross-file bodies - landing near the cheap cells' 154k/5. Across the dataset this attacks
the two largest collapse bigrams (`locate_wire->locate_wire` 79, `read_body->read_body` 19) directly.

## 7. Suggested validation (token-frugal)
Implement A1 + B2 + C1 first (one bridge change + two rule lines - the cheapest, highest-ROI set).
Re-run the battery (offline) + the SAME 3 retrieval queries at n=1 (6 cells) and compare calls/tokens
to this baseline. Only add A2/B1 if the multi-symbol cell hasn't collapsed to <=2 map calls.
