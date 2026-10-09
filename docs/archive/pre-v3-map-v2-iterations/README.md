# Archive — pre-v3 Map v2 "configs" design iterations

These documents record an **intermediate design iteration** between the old pack ladder and the
shipped Map v3 product: a prototype `map` with a small set of configs explored in the Claude SDK
harness (`scripts/claude_sdk_harness/map_v2_bridge.py`).

That prototype went through several config shapes — five configs (`find`/`refs`/`open`/`around`/
`outline`), then a collapsed three-config set (`find`/`refs`/`view`) — while measuring agent
over-exploration and token cost in A/B arm tests.

## Why they are here

The product shipped **Map v3** with a **four-config** surface served by
`packages/pipeline/map_v3_server.py`:

- `find` — ranked locations + code inline
- `focus` — symbol body + callers + callees + file siblings (folds in the prototype's
  `open`/`around`/`refs`-relations)
- `related` — related bodies for an anchor + query
- `graph` — abstract files→symbols + call edges, no bodies (folds in `outline`/`around`)

plus `gate` / `status`. The prototype configs `refs` / `view` / `open` / `around` / `outline` are
**not** part of the shipped surface (the v3 server maps a few of those words to a fallback with a
"not a real config" note).

## How to read these

Point-in-time **design-iteration records**. The measurements and conclusions are accurate for the
`map_v2_bridge.py` prototype they were run against, not the shipped tool. For the current surface
see `docs/scubiee-tools-and-usage.md`. The design-rationale doc `docs/scubiee-map-configs.md`
stays in the main docs folder because it already carries a current-v3 reconciliation banner.

## Contents

| File | What it was |
|---|---|
| `scubiee-map-configs-rules.md` | Two-layer prompt for the 3-config (`find`/`refs`/`view`) prototype |
| `scubiee-newmap-3config-arms.md` | Arm test: 3-config map vs old map |
| `scubiee-newmap-vs-oldmap-arms.md` | Arm test: new map vs old map |
| `scubiee-newmap-fewest-calls-arms.md` | Arm test: tuning for fewest calls |
| `scubiee-why-newmap-slower-analysis.md` | Trace analysis of why the prototype was slower |

> Still in the main docs folder (kept, with v3 banners): `scubiee-map-v2-build.md` (historical
> build log that points forward to v3) and `scubiee-map-configs.md` (design study reconciled to the
> shipped four configs).
