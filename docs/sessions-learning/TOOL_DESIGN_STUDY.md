# What tools would actually save tokens? A session-grounded study

Question: given everything we've logged (118 cells), what tool shape lets the agent retrieve what
it needs in the FEWEST API calls? This is analysis only — no new Claude-token-costing runs.
Sources: `data/sessions.jsonl`, `CALL_PURPOSES.md`, `TRAJECTORIES.md`.

---

## 1. First, the consistency check (newmap vs mini_v3, n grown)

| task | arm | n | mean | median | range |
|---|---|--:|--:|--:|---|
| cache_aware (hard, multi-symbol) | mini_v3 | 12 | **418k** | **403k** | 238-785k |
| cache_aware | newmap | 9 | 547k | 554k | 271-765k |
| dirty_files (easy, 1 symbol) | mini_v3 | 7 | 228k | 249k | 146-401k |
| dirty_files | newmap | 6 | **207k** | **191k** | 122-353k |

**newmap is NOT consistently better.** It wins the easy task (within overlapping noise) and
consistently LOSES the hard task (median 554k vs 403k). The earlier "newmap won both" runs were the
low tail of a high-variance distribution. mini_v3 — one map, one whole-file Read, edit — is the
tighter, cheaper arm on the task that matters (multi-symbol edits).

---

## 2. Where do the API calls actually go? (the real signal)

Per-cell average calls by PURPOSE (`CALL_PURPOSES.md`):

| arm | locate_find | read_body | locate_wire | grep_literal | pre-edit locate steps |
|---|--:|--:|--:|--:|--:|
| without | 0.0 | 3.4 | **5.2** | 0.9 | 7.9 |
| mini | 0.9 | 2.9 | **3.6** | 0.3 | 6.6 |
| mini_v3 | 1.1 | 1.8 | 1.5 | 0.5 | 4.8 |
| newmap | 1.0 | 1.5 | 1.7 | 0.0 | 3.8 |

Most common consecutive retrieval steps (collapse targets):

| from -> to | count |
|---|--:|
| **locate_wire -> locate_wire** | **79** |
| locate_find -> read_body | 29 |
| locate_wire -> read_body | 28 |
| read_body -> locate_wire | 19 |
| read_body -> read_body | 13 |

Two cost engines, in order of size:

1. **Wiring traces dominate (`locate_wire -> locate_wire`, 79x).** The agent chains callers/callees/
   uses lookups — grep->grep->grep in the native arms, refs->refs->refs in newmap. This is the
   single biggest repeated step across every arm. In `without` it's 5.2 calls/cell.
2. **Locate-then-read round-trips (`find -> read` 29, `wire -> read` 28).** The agent finds a
   location, then spends a SEPARATE call to see the code. newmap's signature `find -> view` is
   exactly this: it split "where" and "the code" into two calls, which is why it needs 2 calls
   where mini_v3's `map -> Read(whole file)` sometimes needs the Read to also cover siblings.

Even the best arm (newmap) still averages **3.8 retrieval calls before the first edit**. That is the
number a better tool must drive toward 1.

---

## 3. What this says the tools should be

The data does NOT support "more configs." newmap has 3 configs and its cost came from the agent
USING them (find+view+refs = 3 calls). The data supports **fewer calls that each return more of
the right shape**. Two tool capabilities would collapse the two cost engines above:

### Tool A — one call returns code + wiring together (kills `find->read` and `wire->wire`)
The winning move must be: **one call that returns the target symbol's body AND its one-hop wiring
(callers + callees with their file:line) AND the sibling symbol names in the same file** — so the
agent never needs a second `view`/`refs`/grep to understand the neighborhood. This is the
`locate_wire -> locate_wire` (79) and `find -> read` (29) collapse in one object:

```
map(query, names=[...], include_bodies=true)
-> { bodies: [<clustered symbol source>],
     wiring:  { callers: [file:line in fn], callees: [file:line] },   # the 79x collapse
     siblings:[names of other symbols in the file] }                  # the overview, cheap
```
mini_v3 already approximates this by accident (it reads the whole file, which contains the siblings
and often the callees). The explicit version is cheaper than a whole-file Read because it's
names+bodies-of-the-relevant-few, not the entire file.

### Tool B — a cheap, wide "neighborhood overview" for the UNKNOWN-location opener
When the agent does NOT know where to go, the expensive pattern is explore-by-grep. A single
**overview**: top file + 3-5 related files, each as a LIST OF FUNCTION/CLASS NAMES (no bodies),
is a one-call abstract map that replaces the opening grep/find/view exploration. ~1.5-3k chars,
far cheaper than reading files to orient. This is your "small graph of files around it with
function names" idea — and the call-purpose data backs it: it attacks the pre-edit locate steps
(3.8-7.9) by giving orientation in one wide-but-shallow call instead of several narrow ones.

### What NOT to add
- Not a separate `callers` config and a separate `view` config and a separate `find` config — the
  agent spends one call on each (that is literally newmap's 3-call loss). Fold wiring INTO the
  body-returning call (Tool A).
- Not bodies-only (that was mini_plus — it still grepped for call sites, `read_body->locate_wire`
  = 19). Wiring must ride along with the body.

---

## 4. The 2-3 input / 2-3 output shape that fits the data

ONE `map` tool. Inputs and outputs chosen so each call returns a COMPLETE unit of understanding:

Inputs (what you know):
- `query` - semantic, when you don't know the location.
- `names` - exact identifiers you'll touch (anchor + guarantees their bodies/wiring).
- `include_bodies` / `view` flag - whether you want full source or just the map.

Outputs (what you get back), picked by the inputs, never more than one call each:
- `overview` (Tool B): query, no names -> neighborhood graph (files + symbol-name lists, no bodies).
  "I don't know where to go." ONE wide call.
- `focus` (Tool A): query+names or include_bodies -> clustered bodies + one-hop wiring + siblings.
  "Give me the code and how it's wired, ready to edit." ONE call, then EDIT.
- `locate` (fallback): names only, no bodies -> just ranked locations (cheap pointer) when the
  agent truly only needs a line number.

The hard part, confirmed by every run: **this only works if the rules make the agent pick ONE
output and STOP.** newmap failed not because its configs were wrong but because the agent used
three. So the rule must be a hard count: `overview` (if lost) -> `focus` -> EDIT. Two calls max for
a multi-file change; one for a single-file change. The instruction must forbid the
`focus`-then-`refs`-then-`view` chain that the 79x `wire->wire` and newmap's traces show.

---

## 5. Recommendation

Build ONE arm that is **mini_v3's cheap single-call instinct + Tool A's wiring-in-the-body-call**:
a map that, on `include_bodies`, returns the clustered bodies PLUS a compact `wiring` block
(callers/callees file:line) PLUS `siblings` (symbol names in the file) — so the agent gets the
whole neighborhood in ONE call and never chains `wire->wire` or splits `find->read`. Keep `overview`
as the only other output, for the unknown-location opener. Rules: pick one, stop, edit.

Expected effect from the collapse counts: removing the 79 `wire->wire` and 57 `*->read` second
calls is the bulk of the pre-edit locate steps above 1. If the rule holds the agent to one `focus`
call, the hard-task arm should land near mini_v3's cheap cluster (~240-290k) WITHOUT mini_v3's
whole-file-Read waste or newmap's 3-call tax.

Testing plan (token-frugal): build + offline battery + ONE smoke cell per task (not n=3). Only
expand if the single cell shows the one-call `focus->edit` shape.
