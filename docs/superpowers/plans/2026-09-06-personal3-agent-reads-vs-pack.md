# Agent native reads vs pack (personal 3)

Summary judgments: ['pack_partially_useful', 'pack_missed_key_reads', 'pack_highly_useful']

Avg agent read chars: **10402.3**
Avg pack body chars: **4322.0**
Avg pack file-cover of agent reads: **0.417**

## p01 — I need to figure out how the tool gets wired into my editor when I connect it.

**Judgment:** pack_partially_useful

- Agent spans: 6 (306 lines, 10165 chars)
- Pack bodies: 4 (5073 chars)
- Pack covers agent files: 0.333
- Agent-only files: ['packages/pipeline/__main__.py', 'packages/pipeline/mcp_permissions.py']
- Pack-only files: []
- Span hits: 2

### Agent would read

- packages/pipeline/__main__.py:1706-1744 — cmd_connect entry (1567 chars)
- packages/pipeline/rules_installer.py:1627-1680 — install_tools fan-out (1481 chars)
- packages/pipeline/rules_installer.py:1487-1553 — apply_connected_tools_to_repo (2241 chars)
- packages/pipeline/rules_installer.py:1139-1202 — write_project_gate_rules (2152 chars)
- packages/pipeline/mcp_permissions.py:518-531 — apply_permissions_to_repo_tool_surface (397 chars)
- packages/pipeline/mcp_permissions.py:253-320 — merge_cursor_permissions allowlist (2327 chars)

### Pack returned

- packages/pipeline/rules_installer.py:1139-1202 write_project_gate_rules (2152 chars)
- packages/pipeline/rules_installer.py:266-280 gate_line_for_repo (460 chars)
- packages/pipeline/rules_installer.py:283-289 _project_rules_eligible (220 chars)
- packages/pipeline/rules_installer.py:1487-1553 apply_connected_tools_to_repo (2241 chars)

## p02 — Search feels stale after I edit files — how does refresh / sync decide to update?

**Judgment:** pack_missed_key_reads

- Agent spans: 4 (239 lines, 9572 chars)
- Pack bodies: 4 (1893 chars)
- Pack covers agent files: 0.25
- Agent-only files: ['packages/pipeline/freshness.py', 'packages/pipeline/incremental.py', 'packages/pipeline/sync_loop.py']
- Pack-only files: ['packages/pipeline/project_id.py', 'packages/pipeline/repo_lifecycle.py']
- Span hits: 1

### Agent would read

- packages/pipeline/freshness.py:202-282 — check_freshness strategies (3371 chars)
- packages/pipeline/incremental.py:769-860 — ensure_fresh_for_search gate (3319 chars)
- packages/pipeline/sync_loop.py:713-752 — BackgroundSyncLoop.sync_once (1760 chars)
- packages/pipeline/upgrade_supervisor.py:151-176 — rebuild_embeddings_if_needed (1122 chars)

### Pack returned

- packages/pipeline/upgrade_supervisor.py:151-176 rebuild_embeddings_if_needed (1122 chars)
- packages/pipeline/project_id.py:220-226 load_registry (319 chars)
- packages/pipeline/repo_lifecycle.py:98-107 _entry_managed (384 chars)
- packages/pipeline/repo_lifecycle.py:34-35 _root (68 chars)

## p03 — I want to understand how a pack request turns a seed into a small set of code bodies.

**Judgment:** pack_highly_useful

- Agent spans: 5 (321 lines, 11470 chars)
- Pack bodies: 4 (6000 chars)
- Pack covers agent files: 0.667
- Agent-only files: ['packages/pipeline/__main__.py']
- Pack-only files: []
- Span hits: 2

### Agent would read

- packages/pipeline/locate_cli.py:179-227 — cli_pack wrapper (1627 chars)
- packages/pipeline/__main__.py:1655-1695 — cmd_pack CLI (1551 chars)
- packages/pipeline/context_trace.py:1100-1220 — run_pack_context core (4464 chars)
- packages/pipeline/context_trace.py:955-1035 — run_collect_hot bodies (2873 chars)
- packages/pipeline/locate_cli.py:230-258 — cli_expand follow-up (955 chars)

### Pack returned

- packages/pipeline/locate_cli.py:179-227 cli_pack (1627 chars)
- packages/pipeline/context_trace.py:57-93 _trace_engine (1050 chars)
- packages/pipeline/context_trace.py:276-355 _load_repo (2689 chars)
- packages/pipeline/locate_cli.py:230-258 cli_expand (634 chars)
