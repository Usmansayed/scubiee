# Locate calibration — Phase B (post seed-symbol fix)

**Status:** draft v3 · **not a ship decision**  
**Tax:** 2500/round · **Map source:** cli_map=26 lexical_fallback=2  
**M1:** 12 · **Needle/name:** 4 · **E1/C1:** skipped this beat  

## Product fix shipped (code)

Map cards / `suggested_seed` now carry real symbols + line spans:

- `symbol_from_preview` / `fill_map_card_symbol` in `context_trace.py`
- `cli_map` uses hit `start_line`/`end_line` + preview parse (was hardcoded `:1-1` + empty symbol)
- MCP `_enrich_map_cards` + soft search results also fill symbols
- `pick_suggested_seed` prefers public names (skips `_helpers` in primary pass)
- `resolve_seed_node` uses covering def when only `start_line` is known

Taxonomy spot-check: `docs/superpowers/plans/2026-09-07-locate-taxonomy-spotcheck.md` (9/10 OK).

## Scoreboard (M1 / N1)

| Arm | n | total_proxy | rounds | must_file | must_sym | ok |
|-----|--:|----------:|------:|----------:|---------:|---:|
| `M1a_map_read` | 12 | 18251 | 6.0 | 0.875 | 0.283 | 1.0 |
| `M1b_map_pack` | 12 | 22469 | 6.3 | 0.875 | 0.450 | 1.0 |
| `N1a_host_grep` | 4 | 7536 | 2.8 | 1.0 | 0.867 | 1.0 |
| `M2b_map_on_needle` | 4 | 12239 | 4.0 | 1.0 | 0.467 | 1.0 |

**Over-use (needles):** 0.75  
**seed_ok:** 10/12 true (was 0/12)

## Draft findings (P1 unlocked)

1. **Seed fix works** — `seed_ok` 10/12; map symbols no longer empty by default.
2. **P1 conditional pack (seed_ok alone)** — on seed_ok cases, pack was cheaper only **1/10**; mean Δtotal ≈ **+5744**. File recall tied (`pack_better_file=0`, `pack_worse_file=0`). Pack still lifts `must_sym` (0.45 vs 0.28). **Do not Prefer-always-pack on seed_ok from cost alone** — pack earns symbol density, not cheaper proxy.
3. **Needles** — Grep still wins; over-use 75%.
4. **Index fragility** — force `scubiee index --force` failed (DML capability gate); sync-now required explicit full index (>10k chunk delta). Calibration still usable via cli_map once publication recovers.

## Next

- Phase C live A/Bs with Prefer-Grep-on-needles + optional pack for symbol density (not cost).
- Repair durable index publish path (DML preflight / oversized sync).
- No Prefer/Require GATE text until Phase D.

Raw: `docs/superpowers/plans/locate-calibration-phase-b-results.json`
