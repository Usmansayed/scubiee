# Scubiee map versions — full reference

Every map/retrieval variant tested in these sessions, with what it is, its tool surface, its rules,
the bridge file that implements it, and how it performed. This is the key the `data/sessions.jsonl`
`arm` field maps to. All variants are **standalone MCP stdio bridges** that talk to the same running
Scubiee engine over HTTP (`/v1/search`, `/v1/grep`, `/v1/outline`, `/health`); they import nothing
from Scubiee's own `mcp_*` modules, so each arm is isolated and carries only its own rules.

Shared facts across all arms:
- Engine: the live Scubiee server for this repo (`context-engine`), warm/dense, ~8300 chunks,
  version ~0.3.132, HTTP at 127.0.0.1:8765.
- Model under test: `claude-sonnet-5` via claude-agent-sdk.
- Cost law (measured, r=0.978): tokens ~= (context size) x (number of API calls). Fewer calls win.
- Oracle: dev tasks = hidden pytest + real-edit check; retrieval = file-level recall/precision/F1/MRR
  vs a git-pinned gold file set.

---

## Arm `without` — native tools only (control)
- **What:** no Scubiee at all. Agent uses native Grep/Glob/Read/Edit only.
- **Tools:** none from Scubiee.
- **Rules:** none (baseline).
- **Bridge:** n/a.
- **Role:** the floor. Everything is measured against this.
- **Performance:** dev mean **803k tokens / ~18 API calls** (n=10); retrieval mean 359k, precision 0.0
  (names extra files). The most expensive arm by far — grep-chain exploration dominates.

---

## Arm `mini` — OLD map, v2 rules (deprecated baseline)
- **What:** the original single-tool map. One `map(query)` returns ranked location cards
  (`loc`, `symbol`, `score`, `why`) — **pointers only, no code bodies**. Agent must Read the spans.
- **Tools:** `map`, `gate`, `status` (namespaced `scubmini`).
- **Rules:** `RULES`/`INSTRUCTIONS` v2 (`two_layer_v2`).
- **Bridge:** `mini_mcp_bridge.py`.
- **Performance:** dev mean **496k / ~13 calls** (n=7). Strictly dominated by `mini_v3` (same bridge,
  better rules). **Retired as a baseline** — do not use in new arms.

---

## Arm `mini_v3` — OLD map, v3 strict rules  ← current OLD-map baseline / "second best"
- **What:** same old single-tool map as `mini` (pointers, no bodies), but with the tightened v3
  "strictly follow / fewest calls" rules. Its winning move is `map -> Read(whole file) -> Edit`.
- **Tools:** `map`, `gate`, `status` (`scubmini`).
- **Rules:** `two_layer.py` `RULES_V3` / `INSTRUCTIONS_V3` (`policies.RULES['two_layer_v3']`).
- **Bridge:** `mini_mcp_bridge.py`.
- **Strength:** cheap and TIGHT on single-file / multi-symbol edits; high precision on retrieval
  (names only the needed files). Winning dev move reads one whole file in one call.
- **Weakness:** grep-fallback when one Read doesn't cover the task (adds ~158k when it fires);
  high variance.
- **Performance:** dev mean **348k** (n=19) — the cheapest/most consistent map arm on the hard
  multi-symbol task. Retrieval mean 196k, **precision 0.83**, recall 1.0 (n=3).

---

## Arm `newmap` — map_v2, 3 configs (find / refs / view)
- **What:** first multi-config surface. `find` (ranked locations + clustered bodies inline),
  `refs` (a name's defs/uses/callers/callees), `view` (code targets or file/dir outline). Started as
  5 configs, collapsed to 3; `open`/`outline`/`around` alias into view/refs.
- **Tools:** `map` (config=find|refs|view), `gate`, `status` (namespaced `scubiee`).
- **Rules:** `two_layer.py` `RULES_CONFIGS` / `INSTRUCTIONS_CONFIGS` (`policies.RULES['configs']`),
  288 / 1910 tokens.
- **Bridge:** `map_v2_bridge.py`. `find` returns ALL clustered symbol bodies in one call;
  `_append_connections` adds callers/callees to the top find hit.
- **Strength:** `find` returning multi-symbol clustered bodies collapses the find->read round-trip;
  rarely greps.
- **Weakness:** the agent tends to OVER-ask — chains `find -> view -> refs` (3 locate calls) because
  the configs invite "look around". That 3-call tax made it LOSE the hard task vs mini_v3.
- **Performance:** dev mean **411k** (n=15) — more than mini_v3 on average; wins the easy
  single-symbol task, loses the hard multi-symbol task (median 554k vs mini_v3 403k). Known bug fixed
  mid-session: `refs kind=callers names=["bare_name"]` returned "file not found" (now resolves bare
  names to their definition; regression test in the battery).

---

## Arm `mini_plus` — OLD map + include_bodies + names (experiment)
- **What:** the old single-tool map with exactly TWO additions: `include_bodies` (return the top
  symbols' source inline, clustered when several share a file) and `names` (exact identifiers that
  anchor the ranking). Tests whether just-add-bodies closes the gap without a multi-config surface.
- **Tools:** `map` (+ include_bodies, names), `gate`, `status` (`scubmini`).
- **Rules:** `two_layer.py` `RULES_MINI_PLUS` / `INSTRUCTIONS_MINI_PLUS` (`policies.RULES['mini_plus']`),
  290 / 933 tokens. Partner-to-native framing.
- **Bridge:** `mini_plus_bridge.py`.
- **Findings:** `include_bodies` helped (beat plain old map on the clean task, 271k vs 401k). BUT the
  agent did NOT volunteer `names` (a passive optional input goes unused), and bodies-only still left
  the agent grepping for call sites. Conclusion: bodies are worth keeping; a passive `names` input is
  not enough; the call-site/wiring gap is what the next version must fold in.
- **Performance:** dev mean 389k (n=2).

---

## Arm `map_v3` — map_v3, 4 configs (graph / find / focus / related)  ← the NEW map
- **What:** the current new map, designed from the call-purpose study. Each config returns a COMPLETE
  unit so the agent calls ONE and stops, folding wiring INTO the body call:
  - `graph` — abstract JSON: files -> their top-level function/class NAMES + call edges, NO bodies.
    One wide/cheap orientation call for "where do I start".
  - `find` — ranked locations + the relevant symbols' source inline (unknown location, want code).
  - `focus` — ONE unit: a symbol's full code + its callers + its callees + the sibling symbol names
    in its file. Collapses the find->read and the wire->wire chains that the sessions showed were the
    two biggest token leaks.
  - `related` — given an `anchor` chunk you already have + a `query`, the related code elsewhere
    (callers/callees + semantic matches) with bodies. One call instead of a grep-from-here chain.
- **Inputs:** `query`, `anchor` (file::symbol), `names`, `include_bodies`, `scope`.
- **Tools:** `map` (config=graph|find|focus|related), `gate`, `status` (namespaced `scubiee`).
- **Rules:** `two_layer.py` `RULES_MAP_V3` / `INSTRUCTIONS_MAP_V3` (`policies.RULES['map_v3']`),
  296 / 977 tokens. Decision tree keyed on WHAT THE AGENT KNOWS; explicit focus-vs-find boundary
  (can you NAME it -> focus; only describe -> find); partner-to-native; pick-one-act-stop.
- **Bridge:** `map_v3_bridge.py` (reuses the validated map_v2 helpers; adds focus/related/graph).
- **Health:** manual MCP-stdio check all 4 configs OK; live Claude probe `ok:true`, all 4 configs
  invoked, 0 trace errors, agent `all_usable:true`.
- **Performance (retrieval, n=3):** mean **176k tokens / 5.7 calls / 0.33 Read calls**, recall 1.0,
  MRR 1.0 — CHEAPER than mini_v3 (196k / 6.3 / 2.7) with full recall. **Precision 0.56** (vs mini_v3
  0.83): `graph`/`related` surface correct-neighbor files not in the strict git-gold set, so it casts
  a slightly wider net. No dev-task cells yet.

---

## Head-to-head summary (as of this writing)

| arm | surface | bridge | dev mean tok | retrieval mean tok / recall / prec | standing |
|---|---|---|--:|---|---|
| without | native only | - | 803k | 359k / 1.0 / 0.0 | control (floor) |
| mini | old map, v2 rules | mini_mcp | 496k | - | retired |
| mini_v3 | old map, v3 rules | mini_mcp | **348k** | 196k / 1.0 / **0.83** | OLD baseline; tight+precise, cheapest on hard edit |
| newmap | map_v2 find/refs/view | map_v2 | 411k | - | over-asks (3-call tax); wins easy, loses hard |
| mini_plus | old map + bodies + names | mini_plus | 389k | - | bodies help; passive `names` unused |
| map_v3 | map_v3 graph/find/focus/related | map_v3 | - | **176k** / 1.0 / 0.56 | NEW; cheapest + full recall, wider net (lower precision) |

Open threads: map_v3 has no dev-task cells yet (only retrieval); its precision-vs-cost trade needs
more queries to settle; the hard dev task is still confounded by a pricing sub-question (see
LEARNINGS P7 / RESEARCH_REPORT M4). Numbers are small-n; treat as directional.

Regenerate the data behind this doc:
`python docs/sessions-learning/extract_sessions.py && python docs/sessions-learning/mine_patterns.py`
