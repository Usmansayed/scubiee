# Personal 3: map vs map+pack

Blind enrich queries (no known paths/symbols). Full JSON: `docs/superpowers/plans/2026-09-06-personal3-map-vs-pack.json`

Wall: **14.24s**

## Summary

- map avg cards: 12.0
- pack avg bodies: 4.0
- pack avg body chars: 4322.0
- verdicts: ['pack_better_for_exact_edit', 'pack_better_for_exact_edit', 'pack_better_for_exact_edit']

## p01 — I need to figure out how the tool gets wired into my editor when I connect it.

**Enrich:** `when I run connect how does the tool install into the editor write mcp config permissions allowlist auto approve project rules gate text so the agent can call locate tools`

### Map-only (k=12)
- files: `['tests/test_setup_no_mcp.py', 'packages/pipeline/tool_registry.py', 'packages/pipeline/mcp_permissions.py', 'packages/pipeline/rules_installer.py', 'tests/test_mcp_permissions.py', 'scripts/kiro_mcp_ab_dev_eval.py', 'packages/pipeline/__main__.py', 'packages/pipeline/locate.py']`
- symbols on cards: `['', '', '', '', '', '', '', '']`
- bodies/chain: no / no · 6.251s

### Map + pack_context
- chunks: `['write_project_gate_rules', 'apply_connected_tools_to_repo', 'resolve_mcp_project_write_targets']`
- pack symbols: `['write_project_gate_rules', 'gate_line_for_repo', '_project_rules_eligible', 'apply_connected_tools_to_repo']`
- locs: `['packages/pipeline/rules_installer.py:1139-1202', 'packages/pipeline/rules_installer.py:266-280', 'packages/pipeline/rules_installer.py:283-289', 'packages/pipeline/rules_installer.py:1487-1553']`
- body_chars: **5073** · chain edges: `['seed', 'calls', 'calls', 'seed', 'calls', 'calls', 'calls', 'calls']`
- verdict: **pack_better_for_exact_edit**

## p02 — Search feels stale after I edit files — how does refresh / sync decide to update?

**Enrich:** `after I change code when does background sync or freshness decide the index is stale and refresh embeddings or search without full rebuild`

### Map-only (k=12)
- files: `['packages/pipeline/freshness.py', 'tests/test_freshness.py', 'docs/freshness.md', 'docs/reindexing/index-freshness-agent-trajectory.md', 'docs/research-freshness.md', 'packages/pipeline/incremental.py', 'docs/reindexing/live-reindexing-system-design.md', 'packages/pipeline/upgrade_supervisor.py']`
- symbols on cards: `['', '', '', '', '', '', '', '']`
- bodies/chain: no / no · 0.723s

### Map + pack_context
- chunks: `['rebuild_embeddings_if_needed', 'MemoryGovernor.demote_after_index', 'ensure_fresh_for_search']`
- pack symbols: `['rebuild_embeddings_if_needed', 'load_registry', '_entry_managed', '_root']`
- locs: `['packages/pipeline/upgrade_supervisor.py:151-176', 'packages/pipeline/project_id.py:220-226', 'packages/pipeline/repo_lifecycle.py:98-107', 'packages/pipeline/repo_lifecycle.py:34-35']`
- body_chars: **1893** · chain edges: `['seed', 'calls', 'calls', 'calls', 'calls', 'calls', 'calls', 'calls']`
- verdict: **pack_better_for_exact_edit**

## p03 — I want to understand how a pack request turns a seed into a small set of code bodies.

**Enrich:** `how does pack take a seed and query then walk calls to build a lean heatmap and return hottest function bodies under a character budget`

### Map-only (k=12)
- files: `['packages/trace_lab/prod_eval.py', 'scripts/smoke_triple_pack.py', 'scripts/blind20_map_chunks_pack.py', 'packages/pipeline/locate_cli.py', 'scripts/blind_map_pack_20.py', 'scripts/blind20_triple_pack_phase1b.py', 'packages/pipeline/context_trace.py', 'packages/trace_lab/pack_bakeoff.py']`
- symbols on cards: `['', '', '', '', '', '', '', '']`
- bodies/chain: no / no · 1.4s

### Map + pack_context
- chunks: `['cli_pack', 'cli_expand', 'cmd_pack']`
- pack symbols: `['cli_pack', '_trace_engine', '_load_repo', 'cli_expand']`
- locs: `['packages/pipeline/locate_cli.py:179-227', 'packages/pipeline/context_trace.py:57-93', 'packages/pipeline/context_trace.py:276-355', 'packages/pipeline/locate_cli.py:230-258']`
- body_chars: **6000** · chain edges: `['seed', 'calls', 'calls', 'seed', 'calls', 'calls', 'calls', 'calls']`
- verdict: **pack_better_for_exact_edit**
