# Should Scubiee's map tool ship 2 configs instead of 4?

**Hypothesis.** The map tool advertises four configs (`find | focus | related | graph`), but mining
every session showed find+focus = ~92% of real usage and graph+related = ~8% (`related` nearly
dead), and on Kiro agents use ONLY `find`. So: strip the advertised surface to **find|focus**, fold
the two rare behaviors into the instructions, and test whether agents do just as well — a smaller
config menu may reduce decision overhead with no capability loss.

## What was built (fully reversible, zero production impact)
- `scripts/claude_sdk_harness/map_v3_bridge_2cfg.py` — a map server that REUSES the exact 4-config
  handlers but advertises only `find|focus`. The schema enum, tool description, and server
  instructions all list two configs; `graph`/`related` still work as hidden aliases that degrade to
  `find`/`focus` (no hard error), and the instructions explain how to express the dropped behaviors
  with a broad `find` query. It spawns the REPO bridge directly — it never touches the installed
  scubiee package or the production `.kiro/settings/mcp.json`.
- Kiro arms `kab_ship_2cfg` / `kab_fewshot2_2cfg` (same rules as their 4-config twins; only the MCP
  surface differs). Cursor arms via a `_2cfg` suffix convention (`_bridge_for_arm`).

## Preflight (everything green before any run)
1. Standalone bridge: initialize advertises find|focus; enum == `['find','focus']`; tools =
   map/gate/status; `find` returns real code; `focus` returns real code; dropped `graph` degrades
   gracefully; bogus config rejected with the 2-config message.
2. Kiro uv-python preflight: the bridge boots + serves find/focus under the uv-tool interpreter the
   kab_*_2cfg agent actually spawns (not just Miniconda).
3. Cursor arm→bridge resolution verified; `k_fewshot2_2cfg` rule text == `k_fewshot2` (clean A/B).
4. Live Kiro smoke test: `kab_fewshot2_2cfg` ran end-to-end, called the 2-config map (`find`),
   oracle 1.0, isolation held.
   (Side note: the engine 409s search calls while it is mid-reindex — my own file writes triggered
   CTX_AUTO_INDEX. Fixed preflight to wait for a settled generation and to pass MINI_REPO; runs must
   start on a settled engine.)

## Kiro result — 4-config vs 2-config, same k_fewshot2 rule, n=4 (`sync_severity_rollup`)

| arm | avg credits | per-rep | avg map calls | native_ops | oracle | success |
|---|--:|---|--:|--:|--:|--:|
| kab_fewshot2 (4-config) | 2.44 | 5.96, 1.37, 1.22, 1.19 | 2.25 | 1.75 | 1.0 | 4/4 |
| **kab_fewshot2_2cfg (2-config)** | **1.08** | 1.11, 1.27, 0.97, 0.98 | 2.0 | 1.75 | 1.0 | 4/4 |

**Config actually chosen (both arms): `find` on every single cell — zero focus/graph/related.**
This is the key evidence: dropping three configs cost nothing because Kiro agents were only ever
using `find`. Correctness (oracle 1.0) and native_ops (1.75) are identical across arms.

**Reading the credit gap honestly.** The headline 2.44 vs 1.08 (~56%) is inflated by ONE 5.96-credit
outlier in the 4-config arm. Drop the single worst rep from each arm and it's ~1.26 (4-cfg) vs ~1.05
(2-cfg) — a modest ~17% edge. The robust, trustworthy claims are:
1. **2-config is at least as cheap** as 4-config (never worse across 4 reps).
2. **2-config is markedly lower-variance** (0.97–1.27 vs 1.19–5.96) — a smaller menu gave more
   predictable runs.
3. **Zero capability/correctness loss** — same edits, same oracle, same `find`-only tool choice.

All 8 cells isolated (`identical_tree: True`); repo clean before and after.

## Verdict (Kiro)
Stripping map to **find|focus is a safe win on Kiro**: equal-or-cheaper cost, lower variance, no
correctness or capability loss, and a simpler surface. The dropped configs were dead weight on Kiro.

## Cursor result — the stress test (4-config vs 2-config, same k_fewshot2 rule, n=2, `sync_severity_rollup`)

Cursor is the one runtime that actually uses `focus` (~37% of its map calls in the mining), so it is
the real stress case. Tokens are lower-noise than Kiro credits.

| arm | avg tokens | per-rep | map calls | configs chosen | oracle |
|---|--:|---|--:|---|--:|
| k_fewshot2 (4-config) | 212,562 | 213,557 / 211,567 | 2, 1 | find+focus, find | 1.0 |
| k_fewshot2_2cfg (2-config) | 212,325 | 187,567 / 237,083 | 1, 1 | find, **focus** | 1.0 |

1. **Token tie** (212,562 vs 212,325 — identical within noise). No penalty, no clear win on Cursor
   tokens. The 2-config reps straddled the 4-config mean (187k and 237k).
2. **`focus` still worked under the 2-config surface** — in 2cfg r2 the agent chose `focus` and
   succeeded (oracle 1.0). This is the whole point of the stress test: `focus` is one of the TWO
   configs we KEPT, so Cursor keeps the exact config it relies on. We dropped only graph/related,
   which Cursor used rarely. Dropping to find|focus does not cost Cursor its focus capability.
3. **Correctness identical** — all 4 cells oracle 1.0, 2 edits each.
4. **Clean teardown** — the global `~/.cursor/mcp.json` was restored to its exact pre-run state
   (none existed; none exists now); backup removed; no production residue.

## FINAL VERDICT — ship the 2-config surface (find|focus)
Across both runtimes, dropping `graph`+`related` to advertise only **find|focus**:
- **Kiro**: equal-or-cheaper credits, markedly lower variance, agents only ever used `find` anyway.
- **Cursor**: token-neutral, and crucially PRESERVES `focus` (the config Cursor actually uses).
- **Both**: zero correctness loss (every cell oracle 1.0), simpler surface, less decision overhead.

The 4-config design was carrying two dead configs (`related` was near-zero usage everywhere; `graph`
only ~5%). A 2-config map is the right surface: it keeps the two configs that do ~92% of real work
and never measurably hurt, while shrinking the menu the agent (and the rules/instructions) must
reason about. Recommended rollout: fold the rare behaviors into the server instructions (as the
2cfg bridge already does — "orient with a broad find query; focus for a named symbol") and advertise
find|focus only. Keep graph/related as hidden graceful fallbacks so no legacy call hard-errors.

### Caveats
- n=2 (Cursor) / n=4 (Kiro), one integration task. The Kiro headline 56% gap was outlier-inflated;
  the honest Kiro edge is ~17% + lower variance. Cursor is a clean tie. The claim is "2-config is at
  least as good and simpler," not "2-config is dramatically cheaper."
- This measures agent BEHAVIOR with the stripped surface. If you ship it in the real product, re-run
  on a couple more task shapes (a pure retrieval task and a greenfield task) to confirm the tie holds
  where `focus`/`graph` might have mattered more.
- Fully reversible: delete `map_v3_bridge_2cfg.py` + the `_2cfg` arms; nothing else changes. The
  production installed package and mcp.json were never touched.


---

# Tuned 2-config rule (`k_2cfg`) + WITH-vs-WITHOUT Scubiee

The earlier 2-config runs reused `k_fewshot2`, a rule written for the FOUR-config world (it still
names graph/related). A rule that matches the tool exactly should do better. `k_2cfg` (in
`cursor_rules.py`) is purpose-built for find|focus:
- Names ONLY `find` and `focus`.
- Teaches the two FOLDED behaviors: orient a wide area with a BROAD `find` query (no graph step);
  pull code near a chunk you hold by putting its names in a `find` query (no related step).
- Keeps the proven discipline: known literal/path → native; act on the result, don't re-search;
  greenfield → no map.
- Examples: positive (find wins) + a KNOW-THE-NAME focus case + negative (greenfield). The focus
  example is deliberate — we want the agent to actually reach for `focus`.
It is much leaner than k_fewshot2 (Kiro prompt 3,510 vs 10,388 chars) because it drops the generic
4-config manual.

Arms: WITH = 2-config bridge + k_2cfg rule (`kab_2cfg` / Cursor `k_2cfg`). WITHOUT = native tools,
no Scubiee (`kab_without` / Cursor `without`). Without-arm runs FIRST. Task `sync_severity_rollup`.

## Kiro — WITH vs WITHOUT (n=3)
| arm | avg credits | per-rep | map calls | configs | native_ops | oracle |
|---|--:|---|--:|---|--:|--:|
| kab_without (native) | 4.31 | 4.09, 4.25, 4.58 | 0 | — | 7.0 | 1.0 |
| **kab_2cfg (Scubiee + k_2cfg)** | **1.08** | 0.96, 1.09, 1.19 | 3.33 | find+focus | 2.0 | 1.0 |

**Scubiee + the tuned rule was ~4× cheaper than native** (1.08 vs 4.31 credits), both arms tight (no
outliers), same correctness (oracle 1.0). native_ops collapsed from 7 → 2: map SUBSTITUTED for
native searching rather than supplementing it. And the tuned rule finally got **Kiro to use `focus`**
(`cfg={'find':2,'focus':1}` and `{'find':3,'focus':1}`) — earlier Kiro runs were find-only. The
explicit KNOW-THE-NAME → focus example did the work.

## Cursor — WITH vs WITHOUT (n=2, tokens)
| arm | avg tokens | per-rep | map calls | configs | oracle |
|---|--:|---|--:|---|--:|
| without (native) | 269,120 | 186,748 / 351,492 | 0 | — | 1.0 |
| **k_2cfg (Scubiee + k_2cfg)** | **219,624** | 213,289 / 225,960 | 2 | find+focus | 1.0 |

**Scubiee was ~18% cheaper on tokens AND far more stable.** The native arm swung 187k→351k (a lucky
cheap search vs a 351k-token grep-walk); Scubiee capped that downside (213k/226k, tight). Both k_2cfg
reps used **find+focus** — the agent reached for `focus` on the known-symbol part and `find` on the
discovery part, exactly the intended 2-config behavior. All cells oracle 1.0.

## Bottom line
The surface-matched `k_2cfg` rule makes the 2-config Scubiee a clear WITH-beats-WITHOUT win on both
runtimes for integration work: ~4× cheaper on Kiro credits, ~18% cheaper + much lower variance on
Cursor tokens, identical correctness. The fine-tuning also fixed the earlier Kiro `focus` blind spot.
This is the configuration to carry forward: 2-config map surface + the k_2cfg rule/instructions.
Clean teardown both runtimes (global ~/.cursor/mcp.json restored; repo clean); production untouched.

### Caveats (tuned round)
- One integration task; n=3 Kiro / n=2 Cursor. Integration is map's best case — the with/without gap
  will be smaller on edits and ~zero on greenfield (nothing to locate). Worth a retrieval-only and a
  greenfield with/without run before generalizing the "4× / 18%" numbers.
- Credits ≠ tokens; compare within a runtime only.
