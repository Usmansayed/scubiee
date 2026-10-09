# Rules and instructions for the 3-config map

The two-layer prompt for `map_v2_bridge.py`. Three configs: `find`, `refs`, `view`.

| Layer | Role | Cap | Measured |
|---|---|---|---|
| RULES | persistent anchor (the config picker + hard rules) | < 300 tokens | **284** |
| INSTRUCTIONS | operating manual (a worked example of each config) | < 2000 tokens | **1383** |

Source: `scripts/claude_sdk_harness/two_layer.py` (`RULES_CONFIGS`, `INSTRUCTIONS_CONFIGS`), wired as the `configs` arm in `policies.py`. Token check: `check_two_layer.py`.

The caps were raised from 200/1000 (single-map tool) because there are now configs to explain. The instruction budget is spent on **one worked example per config** — real arguments and the actual response shape — so the agent sees exactly what each returns and how to act on it, rather than an abstract description.

## The three configs (and what the five collapsed into)

| config | Answers | Absorbed |
|---|---|---|
| `find` | "where is the code for X?" (you don't know the location) | — |
| `refs` | "a name's definitions, uses, and relations" | old `around` (relation kinds: callers/callees/tests/siblings) |
| `view` | "show me this" — code of named targets, or the structure of a path | old `open` (targets) + `outline` (path) |

Why three, not five: the first live arm test showed the agent over-exploring — after `find` already answered a task it still called `around` and three `refs` before editing. Fewer configs means fewer side-trips. All capability is kept; `open`/`outline`/`around` still alias.

## RULES (284 tokens)

```text
Scubiee `map` is your PRIMARY tool for finding and reading code. It has three configs; pick by what
you already know:
- Don't know where the code is -> map config=find (query = short intent; keywords = exact names you
  know). find returns ranked locations AND the top result's code inline. If that is the place you
  need, EDIT it now - do NOT view it again or call another config to look around.
- Know a name, want its definitions / uses / imports / callers / callees / tests -> map config=refs
  (names, kind=all | def | uses | imports | callers | callees | tests | siblings).
- Want to SEE code or structure -> map config=view: targets=["file::symbol","file:line",...] shows
  the code (pass SEVERAL at once); path=<dir-or-file> shows the outline.

MUST: to find where code lives, use map, not grep/glob. After a map result, do NOT grep, re-map, or
call another config to "confirm" it. Read only spans you will use; never read a whole file when you
have a line range; never read a listed test/doc file. Stop retrieving and EDIT the moment you can.
A known literal string, or a path you already have -> native Grep / Read.
```

## INSTRUCTIONS (1383 tokens)

The manual gives each config a block with: its arguments, a real call, the **actual response shape** (captured from the live bridge), and a "how to act" line. Then the hard MUST/MUST-NOT rules, the stay-native cases, and good/bad trajectories labelled with call counts.

```text
## Scubiee map - operating manual (3 configs: find, refs, view)

Cost model: each model turn re-reads the whole conversation, so cost ~= context x turns. The waste
is (1) extra round-trips and (2) files you read but never edit. map is built so ONE call answers the
question. So: prefer a single complete call over a lean one that makes you ask again, and ACT on the
first good answer instead of looking around. A few thousand extra characters paid once beats a turn.

Pick the config by what you know: don't know where it is -> find; know a name -> refs; can name what
to see -> view.

========================================================================
find - "where is the code for X?"  (you don't know the location)
========================================================================
Args: query = short plain-language intent (required); keywords = exact names you know (optional,
weighted); scope = code|tests|docs|all (default code).
Call:  map config=find query="where idle shutdown retires the engine" keywords=["_retire_self"]
Returns ranked results (matched line per hit) and, when confident, the TOP result's full function
inline, plus a confidence level:
    find: 8 results  confidence: high - all keywords match in packages/pipeline/server.py::_retire_self
    1. packages/pipeline/server.py:791-812  _retire_self  [keyword+semantic]
       791: def _retire_self() -> bool:
    2. packages/pipeline/server.py:815-937  _start_idle_sweeper  [keyword]
    ...
    -- body of packages/pipeline/server.py::_retire_self --
    791: def _retire_self() -> bool: ...<full function>...
How to act: the body is right there. If it's the place you need, EDIT IT NOW. Do NOT view that span
again, and do NOT call refs/view "to look around" first. Only call another config if find did not
give you what you need. confidence: low or no match -> rewrite query with new words, or use refs if
you actually know a name.

========================================================================
refs - "a name's definitions, uses, and relations"  (you know the name)
========================================================================
Args: names = one or more identifiers (required); kind = all | def | uses | imports (occurrences)
| callers | callees | tests | siblings (relations); scope default code.
Occurrence call:  map config=refs names=["git_dirty_files"] kind=uses
    git_dirty_files - 1 def, 31 uses, 2 imports (code 2, tests 3, docs 17)
    uses:
      packages/pipeline/freshness.py:223  in check_freshness  dirty = git_dirty_files(root) ...
      tests/test_freshness.py:159  in test_git_dirty_keeps_the_first_filename_intact  assert ...
Relation call:  map config=refs names=["freshness.py::git_dirty_files"] kind=callers
    callers (1):
      packages/pipeline/freshness.py:223  in check_freshness  dirty = git_dirty_files(root) ...
How to act: use refs before a rename or signature change (kind=all or uses gives every site), or to
understand wiring (kind=callers/callees/tests). This REPLACES a grep chain - never grep a name you
can pass to refs. Then `view` the few sites you must change (batch them).

========================================================================
view - "show me this"  (you can name it)
========================================================================
Code mode - Args: targets = ["file::symbol" | "file:line" | "file:a-b", ...]. PASS SEVERAL AT ONCE.
Call:  map config=view targets=["freshness.py::git_dirty_files","server.py:800"]
    == packages/pipeline/freshness.py::git_dirty_files  lines 105-139
    105: def git_dirty_files(root: Path) -> list[str]: ...<function + small margin>...
Returns each target's enclosing function; a bare file:line expands to the function containing it;
already-shown spans are skipped. Structure mode - Args: path = a directory or file; query filters.
Call:  map config=view path="packages/pipeline/freshness.py"
    outline packages/pipeline/freshness.py  (343 lines, 11 symbols)
      33-71  class FreshnessReport:
      105-129  def git_dirty_files(root: Path) -> list[str]:
      ...
How to act: view targets when you already know the exact places (several in ONE call, not one per
turn). view path when you need a file's shape or a directory's contents - it replaces ls/find/tree.

Hard rules (MUST / MUST NOT):
- To DISCOVER where code lives, use map, not grep or glob.
- MUST NOT, after a map result, grep / re-map / call another config to "confirm" or "look around" -
  it already answered you; another call is a wasted turn with no new information.
- MUST NOT view or Read a span find already returned inline.
- MUST NOT read a whole file when you have a line range, or a test/doc file just because it was
  listed.
- Batch: several targets in one view, several names in one refs.
- Stop retrieving and EDIT as soon as you can.

Stay native when cheaper: exact literal string/regex you know -> Grep; change history -> git;
a span whose exact line range you already have -> Read.

Good trajectories (count the calls):
- find query=... keywords=[...] -> body returned -> EDIT.                              (1 call)
- refs names=["X"] kind=all -> edit each site.                                         (1 to locate)
- view targets=["a.py::f","b.py::g","c.py:120-160"].                                   (1, not 3)
- refs names=["handler"] kind=callers -> view the 2 callers you must change.           (2 calls)

Bad trajectories (never):
- find returned the body, then you view/Read it again or call refs "to be sure" before editing.
- find, then grep the same name "to make sure".
- view a.py; next turn view b.py; next turn view c.py.   (3 turns for 1 call of work)
- grep -> grep -> grep to trace callers instead of one refs.
- Read a 1500-line file after a result handed you a 30-line range.
```

## Design notes

- **Config picker leads both layers.** It's the one decision the agent makes every call.
- **Each config shows its real response.** The response shapes above were captured from the live bridge, not invented, so the agent is trained on exactly what it will receive. This is where the raised budget went.
- **"How to act" after every example.** The waste is always in what the agent does *after* a result, so each block ends with the action to take — and, for `find`, the explicit "EDIT, don't look around" that the arm test showed was missing.
- **Trajectories carry call counts.** The quantity to minimise is model calls, so good/bad examples are labelled with them.
- **Hard rules are a separate MUST/MUST-NOT block**, so the model can override a preference but not a rule.

## Status

- Written and token-checked (284 / 1383). Wired as the `configs` arm.
- The tool itself is verified (offline 24/24, SDK-spawn preflight all green, live Claude probe passed on the earlier 5-config build).
- **These instructions have not yet been run with a real agent.** The open question is whether they stop the over-exploration the first arm test showed. That's the next A/B: old map + v3 vs new 3-config map + these rules, both tasks, n>=3.
