# Which map configs do agents actually use? (mined from all sessions)

**Question:** The new map tool advertises 4 configs — are agents actually using all four, or
collapsing onto one? Answered from data, not memory.

**Surface being measured.** The production `map_v3` server exposes **ONE tool, `map`, with four
configs**: `find | focus | related | graph`. (It is not four separate tools.) The retired `map_v2`
server had a different trio — `find | refs | view` — so older sessions show those names too; they
are kept separate below.

**Source.** `scripts/claude_sdk_harness/mine_map_configs.py` walked every `report.json` under
`.ab_workspaces/claude_sdk_harness` and tallied each cell's recorded `config_use` and
`scubiee_tools_used`.

## Corpus
- reports scanned: **160** (108 carried per-cell data)
- cells total: **449**; cells that fired map ≥1: **217** (~48% of cells call map at all)
- total `map` tool calls: **346**

## Config breakdown — CURRENT map_v3 surface only (278 calls)
| config | calls | share | what it's for |
|---|--:|--:|---|
| **find** | 185 | **66.5%** | "where is X" by description → ranked locations + code inline |
| **focus** | 70 | **25.2%** | a named symbol's body + callers/callees/siblings in one unit |
| graph | 17 | 6.1% | abstract map of a wide/unknown area (names + edges, no bodies) |
| related | 6 | 2.2% | given a chunk you hold, pull the related code |

- **find + focus = 91.7%** of all map usage. These two carry essentially the whole workload.
- **graph + related = 8.3%** combined — the long tail. `related` is nearly vestigial (6 calls ever).

## By runtime (current surface)
- **cursor-cli** (143 calls): find=78, focus=53, graph=6, related=6 — the ONLY runtime that
  meaningfully exercises `focus` (37%) and the only one to ever call `related`.
- **kiro-cli** (60 calls): find=49, graph=11 — Kiro agents use **only find and graph**; in all mined
  Kiro cells they never once chose `focus` or `related`.
- (older "unknown"-runtime sessions used the retired v2 names: find=58, refs=14, view=13, plus a
  `?`=39 bucket where the config wasn't recorded.)

## Other scubiee tools (not map)
`status` seen in 27 cells, `gate` in 6. These are health/readiness calls, used sparingly and only
when a rule or situation prompted a readiness check — exactly as intended.

## Takeaways
1. **Agents do NOT use all four configs evenly.** It is effectively a two-config tool in practice:
   `find` (two-thirds) and `focus` (a quarter). `graph` and `related` together are <10%.
2. **`find` is the default reach** — unsurprising, since most "go locate this" asks are descriptive.
   `focus` only gets picked when the agent already holds symbol names (and really only Cursor does
   this today).
3. **Kiro leaves `focus`/`related` on the table entirely.** Kiro agents collapse to find (+a little
   graph). This is a rule/prompt-shaping opportunity: the `focus`-when-you-know-the-name example in
   k_fewshot (EXAMPLE 2) is not changing Kiro behavior — Kiro still finds instead of focusing.
4. **`related` barely justifies its slot** (6 calls across every session ever). If the 4-config
   surface is costing prompt/description tokens or decision overhead, `related` is the first
   candidate to fold into `find`/`focus` or drop.

## Caveats
- `config_use` was recorded on 217 cells; the 39-call `?` bucket is older cells where the config
  label wasn't captured, so true per-config counts are modestly undercounted (not biased toward any
  one config).
- Mixed surfaces: v2 (`refs`/`view`) and v3 (`focus`/`related`) are different servers; the
  "current surface" table above is the one that reflects what ships today.
