# Multi-file dev task: map_v3/U (WITH Scubiee) vs native-only (WITHOUT)

Round of the experiment that answers: **does Scubiee's production prompt (U) help
an agent on genuine multi-file dev tasks, versus the same agent with no Scubiee at
all (native Read/Grep/Glob/Edit only)?**

## Setup (all preflighted offline before any live token was spent)

- **Production prompt under test**: `RULES['map_v3'] == MAP_V3_U` (the "ultimate
  hybrid"). rules=331 tok (<350), instructions=1111 tok (<2000), combined 1442.
- **Arms**:
  - `without` — native tools only, no MCP. Tools: Read/Grep/Glob/Edit/Write/TodoWrite.
  - `map_v3`  — same native tools + the Scubiee map-v3 bridge + the U prompt appended to CLAUDE.md.
- **Model**: claude-sonnet (harness default). **No Bash** in either arm — locate+edit
  only; the hidden oracle does verification, removing the pytest/shell confound.
- **Snapshot**: full repo subtree (packages + tests + docs + scripts) copied per cell,
  git baseline, reset between cells. merkle.py + freshness.py always present.
- **n = 2** repeats per arm per task (the earlier unfair n=1 mistake is not repeated).

### The two tasks (both are GENUINE 2-file edits)

Both target the same proven seam: `SyncDiff` (packages/pipeline/merkle.py) is wrapped
by `FreshnessReport` whose `to_dict()` lives in packages/pipeline/freshness.py. The
correct, natural implementation of each task MUST add an accessor on the diff type
(merkle.py) AND surface it in the report dict (freshness.py).

- **MF1 `total_changed_field`** — expose a single total-changed count = plain
  `len(added)+len(modified)+len(removed)` as a reusable accessor on the diff, then
  surface it in the report dict. Oracle uses an overlap trick so the plain SUM is
  provably distinct from the pre-existing `changed_count` (which is a set-union), i.e.
  the task cannot be satisfied by the field that already exists. Oracle is 3/3 strict.
- **MF2 `root_hash_fingerprint`** — expose a short 12-char fingerprint of the content
  root hash as a reusable accessor on the diff, surface it in the report dict, keep the
  full hash. Oracle grades 2/3 here because the lenient backwards-compat check ("full
  hash still present") is not required by the baseline dict — identical for both arms,
  so it does not bias the comparison.

### Oracle discrimination (proven offline, no AI)

| task | unedited baseline | correct 2-file edit |
|------|-------------------|---------------------|
| MF1  | ok=False (1/3)    | ok=True (3/3)       |
| MF2  | ok=False (1/3)    | ok=True (3/3)       |

A one-file edit cannot pass: the accessor must be on the diff type (merkle.py) **and**
read through to the dict (freshness.py).

## Results (live, n=2)

### MF1 — total_changed_field

| arm | tok mean | calls | map | grep | read | edits | success | oracle |
|-----|---------:|------:|----:|-----:|-----:|------:|:-------:|:------:|
| without | **211,608** | 7.0 | 0 | 2.5 | 1.5 | 2 | 2/2 | 1.0 |
| map_v3  | 226,242 | 7.0 | 2.0 | 0 | 1.0 | 2 | 2/2 | 1.0 |

### MF2 — root_hash_fingerprint

| arm | tok mean | calls | map | grep | read | edits | success | oracle |
|-----|---------:|------:|----:|-----:|-----:|------:|:-------:|:------:|
| without | 275,726 | 8.5 | 0 | 3.0 | 2.5 | 2 | 2/2 | 0.67 |
| map_v3  | **222,343** | 7.0 | 2.0 | 1.0 | 0 | 2 | 2/2 | 0.67 |

## Verdict (honest)

**Correctness: a tie — both arms solved both tasks every time (8/8 cells, correct
2-file edits in all).** On these well-specified, 2-file-seam tasks, Scubiee is not
required for the agent to get the right answer; a capable native agent finds the
`SyncDiff`/`FreshnessReport` seam with Grep + Read.

**Efficiency: task-dependent, net slight win for Scubiee, not decisive at n=2.**
- MF2: map_v3 was clearly leaner — **222k vs 276k tok (~19% fewer)**, 7 vs 8.5 calls,
  and it reached the seam with 2 map calls and **zero** file reads on the clean rep.
  The native arm spent 2.5-3 reads + 3 greps hunting the two files.
- MF1: the native arm was actually a touch cheaper (**212k vs 226k**, ~7% ). Here Grep
  on the literal "changed_count"/to_dict landed immediately, so semantic map bought
  nothing and cost its two calls.
- Across both tasks: without mean ≈ 243.7k, map_v3 mean ≈ 224.3k → **map_v3 ~8% leaner
  overall**, driven entirely by MF2.

**Behavioral signal (consistent with the whole experiment):** the U prompt routes the
agent to `map` and suppresses the grep-shotgun — map_v3 did 0 grep on MF1 and reached
MF2 with 0 reads once. When the target is a plain literal/known symbol (MF1), U
correctly does NOT save calls over native Grep, matching U's own "needles -> Grep"
rule; the benefit shows up when the seam is more semantic (MF2's "short fingerprint of
the content hash" phrasing has no single literal to grep).

**Bottom line:** On genuine multi-file dev tasks with a clear seam, Scubiee/U does not
change *whether* the agent succeeds (native is fully capable here) but it modestly
reduces tokens/calls on the more semantic task and never regressed correctness. The
win is real but small at this difficulty; the larger gains seen earlier require either
harder-to-locate seams or cross-module discovery, not tidy 2-file edits.

### Caveats
- n=2; token counts have real variance (MF2 without ranged 256k-296k, map_v3 185k-260k).
- Both tasks share one seam (merkle<->freshness); a different seam could shift the balance.
- These tasks are deliberately well-specified; they do not probe discovery, which both
  arms still fail elsewhere.


## Why map did NOT beat native on MF1 (trajectory autopsy)

Pulled the recorded tool traces for both arms. The map_v3 arm's *trajectory* was
actually cleaner than native, yet it cost the same or slightly more tokens. Reasons:

**MF1 (literal/greppable target) — map trace (both reps identical):**
```
ToolSearch select:mcp__scubiee__map   (60c)   <- loads the MCP tool def = 1 extra API turn
MAP find  "freshness report dict added modified removed diff" -> 1912c
MAP focus                                       -> 3661c
Read  (one file)                                -> 5669c
Edit ; Edit                                     (2-file edit)
```
**MF1 — native trace (winning rep r2):**
```
Grep "added.*modified.*removed|freshness"       -> 732c
Read (one 14k file)                              -> 14010c
Grep "class SyncDiff|changed_files"             -> 792c
Edit ; Edit
```

Three fixed costs the WITH arm pays that native never does:
1. **ToolSearch tax** — a whole extra API round-trip just to load `map`'s definition
   (each round-trip re-sends the full context).
2. **The 1442-token U prompt** is appended to CLAUDE.md and re-sent on all ~7 turns
   (~10k tokens of pure prompt overhead across the run).
3. **Richer map payload** — find(1912) + focus(3661) = ~5.6k of semantic context the
   agent did not need, because the target symbols (`added/modified/removed`, `SyncDiff`,
   `to_dict`) are plain literals that Grep resolves in one hit.

MF1's target is a **needle** — U's own rule says "needles -> Grep." The WITH arm had
`map` in hand and used it where grep was strictly cheaper. The map calls weren't wrong,
they just had nothing to locate, so their fixed cost was not repaid.

**Contrast — MF2 (semantic target "short fingerprint of the content hash", no literal):**
- map_v3 r1: `find` -> `focus` handed over BOTH file bodies; agent edited with
  **0 grep, 0 Read**, 6 calls, **185k tok** — map fully replaced the hunt.
- native r2: 3 grep + 3 Read, 9 calls, **296k tok**.

**The lever:** map wins exactly when (a) the target is semantic enough that Grep needs
several tries, AND (b) the agent trusts the `focus` payload and skips native reads. It
loses when the target is greppable (MF1) or when the agent redundantly greps after
mapping (MF2 r2: 2 extra greps pushed it to 260k). The first is inherent to easy
literal tasks; the second ("don't re-grep packed ground") is prompt-tunable and is
already a FAIL rule in the Scubiee instructions — the agent just didn't always obey it.
