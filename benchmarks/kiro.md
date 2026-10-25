# Kiro CLI benchmark results

Agent: Kiro CLI (`kiro-cli chat` v2.23.1, headless, model `auto`). Kiro reports cost in
**credits**, its billing unit, rather than raw tokens. The "without" arm uses Kiro's native tools;
the "with" arm adds the Scubiee MCP server (`map` with `find` / `focus`) and its rules.

[Back to summary](README.md)

## Results

| Task | Type | Runs per arm | Without Scubiee | With Scubiee | Saved |
|---|---|---:|---:|---:|---:|
| Sync severity roll-up | Integration across modules | 3 | 4.31 credits | **1.08 credits** | **75%** (4x cheaper) |
| New `health` CLI command | Long two-turn feature build | 4 | 11.24 credits | **4.01 credits** | **64%** (2.8x cheaper) |
| Unify token estimate | Cross-module edit | 4 | 3.70 credits | **2.85 credits** | **23%** (40% at the median) |
| **Average** | | | **6.42 credits** | **2.65 credits** | **54%** per task |

## What changed in the agent's behavior

| Task | Native file operations (without → with) |
|---|---|
| Sync severity roll-up | 7 → **2** |
| New `health` CLI command | ~16 → **~10** |
| Unify token estimate | 4.25 → **2.5** |

- On the feature build, Scubiee also finished about **35% faster** (about 205 s vs 310 s).
- The Scubiee runs on the integration task were tight (0.96-1.19 credits); the native runs were
  all above 4 credits.
- Kiro used Scubiee in every run: the `map` tool replaced native searching rather than adding to it.
