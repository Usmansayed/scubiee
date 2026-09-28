# Native-only context collect (awaiting Scubiee twin)

**Agent:** [Native collect](15507cc0-5b32-4d4a-8101-c0d275f93433)  
**Mode:** no Scubiee (Grep/Glob/Read only)  
**Status:** complete — Scubiee twin done: [Scubiee collect](1c93487b-459d-4f90-93e7-9193543197a6). Compare: `2026-09-06-compare-native-vs-scubiee-cli-heatmap-collect.md`.

## Work prompt

Change Scubiee so CLI `scubiee pack` returns the same compressed heatmap-only agent view as MCP `pack_context` (locs + heat + `read.top`, no bodies by default). Opt-in bodies via env/flag. Touch CLI, slim shaping, `include_bodies` defaults, tests, docs/GATE that still say `pack[].text`.

## Efficiency (self-reported)

- tool_calls: 37
- total_chars_ingested: ~92000
- core touchpoints identified: `locate_cli.cli_pack`, `run_pack_context`, `mcp_response_lean`, `__main__` help, `test_locate_cli`, `rules_installer` GATE, MCP already `include_bodies=False`

## Key finding (for later compare)

CLI `cli_pack` omits `include_bodies` → engine default `True` → bodies; MCP forces `False`. Slim already heatmap-only when `include_bodies` is false. Opt-in env `CTX_MCP_PACK_BODIES` reshapes only if bodies already collected.
