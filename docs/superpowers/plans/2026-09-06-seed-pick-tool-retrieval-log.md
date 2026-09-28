# Seed-pick A/B — tool retrieval log + improvisation notes

**Host tokens:** MCP Scubiee **448k** vs Native **543k** (~17.5% save).

Full machine log: `docs/superpowers/plans/2026-09-06-seed-pick-tool-retrieval-log.json`

## MCP Scubiee ([4195dc84](4195dc84-ba28-4fda-87dd-70c3b49f81a4))

### Tool mix

```
{
  "UpdateCurrentStep": 7,
  "GetDynamicTools": 4,
  "Grep": 7,
  "Read": 9,
  "CallDynamicTool": 4
}
```

### Retrieval timeline (UpdateCurrentStep omitted)

- `03` GetDynamicTools ns=`project-0-context-engine-scubiee` tool=`None` pat=`None`
- `04` Grep `"name": "(gate|map|pack_context|expand_context)"` @ `C:\Users\usman\.cursor\projects\c-Users-usman-Downloads-context-engine\agent-tools\1da192cb-0d8d-412b-9c75-a98e9424febf.txt`
- `05` Read `agent-tools/1da192cb-0d8d-412b-9c75-a98e9424febf.txt` offset=None limit=150
- `06` GetDynamicTools ns=`project-0-context-engine-scubiee` tool=`gate` pat=`None`
- `07` GetDynamicTools ns=`project-0-context-engine-scubiee` tool=`map` pat=`None`
- `08` GetDynamicTools ns=`project-0-context-engine-scubiee` tool=`pack_context` pat=`None`
- `11` **MCP `gate`** seed=`` sym=`` mode=`` dir=``
- `12` **MCP `map`** seed=`` sym=`` mode=`` dir=``
- `15` **MCP `pack_context`** seed=`packages/pipeline/context_trace.py` sym=`pick_suggested_seed` mode=`lean` dir=``
- `18` **MCP `expand_context`** seed=`` sym=`` mode=`` dir=`broad`
- `19` Read `packages/pipeline/context_trace.py` offset=372 limit=61
- `21` Read `packages/pipeline/locate_cli.py` offset=60 limit=117
- `22` Grep `resolve_seed_node|pick_suggested_seed|suggested_seed|_templates_dir|_env_flag|is` @ `C:\Users\usman\Downloads\context-engine\packages`
- `23` Grep `pick_suggested_seed|resolve_seed_node|suggested_seed|card_role` @ `C:\Users\usman\Downloads\context-engine\tests`
- `26` Read `packages/pipeline/context_trace.py` offset=463 limit=100
- `27` Read `packages/pipeline/mcp_locate.py` offset=3510 limit=120
- `28` Read `tests/test_incremental_context_ladder.py` offset=1 limit=100
- `29` Read `packages/pipeline/mcp_response_lean.py` offset=280 limit=50
- `30` Grep `_SKIP_SEED_SYMBOLS|_kind_pref|_enrich_map_cards|def rank_soft_map_cards` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline\context_trace.py`
- `31` Grep `def _enrich_map_cards|def _assess_map_confidence` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline\mcp_locate.py`
- `32` Grep `_SKIP_SEED_SYMBOLS|private|_templates_dir|_env_flag|empty.?symbol|suggested_seed` @ `C:\Users\usman\Downloads\context-engine\tests`
- `33` Read `packages/pipeline/context_trace.py` offset=620 limit=40
- `34` Grep `startswith\(\"_\"\)|private|underscore|_SKIP_SEED` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline`
- `35` Read `tests/test_locate_cli.py` offset=70 limit=40

## Native ([d67754a9](d67754a9-2a53-465c-9372-2cb21c74c334))

### Tool mix

```
{
  "UpdateCurrentStep": 4,
  "Grep": 20,
  "Glob": 2,
  "Read": 24
}
```

### Retrieval timeline (compressed — Grep/Read heavy)

- `03` Grep `pick_suggested_seed|resolve_seed_node|suggested_seed` @ `C:\Users\usman\Downloads\context-engine`
- `04` Grep `cli_map|def map\b|suggested_seed` @ `C:\Users\usman\Downloads\context-engine`
- `05` Glob `**/*seed*`
- `06` Glob `**/*seed*`
- `09` Read `packages/pipeline/context_trace.py` offset=350 limit=220
- `10` Read `tests/test_incremental_context_ladder.py` offset=None limit=None
- `11` Read `packages/pipeline/locate_cli.py` offset=60 limit=160
- `12` Grep `_SKIP_SEED|seed_symbol|role=|kind.*function|_templates_dir|_env_flag|is_transien` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline`
- `13` Grep `pick_suggested_seed|resolve_seed_node|suggested_seed|_SKIP_SEED|private|_templat` @ `C:\Users\usman\Downloads\context-engine\tests`
- `14` Read `packages/pipeline/context_trace.py` offset=600 limit=100
- `15` Read `packages/pipeline/mcp_locate.py` offset=3510 limit=120
- `16` Grep `def run_map_context|def run_pack_context|rank_soft_map_cards|card_role|pick_sugg` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline`
- `17` Read `docs/superpowers/specs/2026-09-05-incremental-context-ladder-design.md` offset=1 limit=80
- `18` Read `tests/test_locate_cli.py` offset=70 limit=80
- `19` Grep `cli_map|rank_soft_map|pick_suggested|resolve_seed|suggested_seed|empty.symbol|st` @ `C:\Users\usman\Downloads\context-engine\tests`
- `21` Grep `def _enrich_map_cards|def _assess_map_confidence` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline`
- `22` Read `packages/pipeline/context_trace.py` offset=1101 limit=120
- `23` Read `packages/pipeline/mcp_response_lean.py` offset=280 limit=80
- `24` Grep `startswith\(\"_\"\)|private.?helper|leading.?underscore|public.?function|empty.?` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline`
- `25` Grep `def _templates_dir|def _root|def write_project` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline\rules_installer.py`
- `26` Read `packages/pipeline/mcp_locate.py` offset=1271 limit=100
- `27` Read `packages/pipeline/mcp_locate.py` offset=1905 limit=120
- `28` Read `packages/pipeline/capability.py` offset=200 limit=40
- `29` Grep `cli_map|seed.symbol|seed_file|pick_suggested` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline`
- `30` Read `packages/pipeline/__main__.py` offset=1635 limit=50
- `31` Grep `rank_soft_map|card_role|_kind_pref|resolve_seed_node|pick_suggested_seed|cli_map` @ `C:\Users\usman\Downloads\context-engine\tests`
- `32` Grep `"kind"|symbol|start_line|role` @ `C:\Users\usman\Downloads\context-engine\packages\pipeline`
- … (more Greps)
- `34` Read `packages/pipeline/mcp_locate.py` offset=1600 limit=80
- `36` Read `packages/pipeline/rules_installer.py` offset=1 limit=80
- … (more Reads)

## Where MCP still burned tokens

1. **4× GetDynamicTools** — schema discovery before each MCP call (should cache once).
2. **7× UpdateCurrentStep** — UI chrome, not locate value.
3. **7× Grep after heatmap** — still shotgunning after pack; pack was only ~620 chars.
4. **9× Read** — more than `read.top=5` (heatmap had 2 hot cards; agent over-read).
5. **expand_context** — extra MCP hop after a thin-but-usable pack.
6. Model reasoning turns between tools — host tokens ≫ tool chars (~18.5k chars vs 448k tokens).

## Improvisation backlog (product + agent policy)

| Change | Why |
|---|---|
| Agent: **one** GetDynamicTools per namespace, then call | Cut schema rediscovery |
| Agent: hard stop after map+pack+≤5 Reads unless expand justified | Cap thrash |
| Agent: ban Grep until top heats Read | Force heatmap use |
| Product: fix MCP `suggested_seed` null (cards need kind/symbol) | Fewer wrong seeds / expands |
| Product: denser heatmap when seed known (include resolve_seed_node neighbors) | One pack enough |
| Skip UpdateCurrentStep in eval agents | Pure token noise |
| Log tool_use + response_chars in harness automatically | Repeatable A/Bs |

