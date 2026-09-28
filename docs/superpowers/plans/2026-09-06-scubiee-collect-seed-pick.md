# Scubiee-first context collect — map→pack seed selection

**Agent:** [Scubiee collect](8a6501bd-e5f2-4604-acdb-d7de7ce69c5e)  
**Mode:** Scubiee CLI map→pack→expand + guided Grep/Read  
**Status:** complete — Native twin done: [Native collect](d0320302-e9f5-4ec6-a3bd-968da20979bb). Compare: `2026-09-06-compare-scubiee-vs-native-seed-pick.md`.

## Work prompt

Improve map→pack seed selection so pack prefers real `packages/` public functions/methods — not empty file-level cards, not private helpers (`_templates_dir`, `_env_flag`, etc.).

## Efficiency (self-reported)

- tool_calls: 22
- total_chars_ingested: ~78500

## Diagnosis (to verify vs Native later)

1. `cli_map` builds empty-symbol `file:1-1` cards labeled `function`
2. `pick_suggested_seed` skips tests/docs but not `_` privates / empty symbols
3. `resolve_seed_node` empty-symbol auto-pick = earliest in-file function (e.g. `_root`)
4. Tests cover packages-over-tests / ROOT, not private/public preference

## Spot-check (parent)

- `pick_suggested_seed` / `resolve_seed_node` / `_SKIP_SEED_SYMBOLS={"ROOT","root"}` present in `context_trace.py` ~358–525 — claims align.
- Ladder reproduced: map → empty symbol `locate_cli.py`; bare pack → `::_root`.
