# Blind-20 map → chunks → pack Phase2

Loop: soft map → select relevant symbol chunks → pack(query+chunks).

**Pack winner:** `pack_context` (symbol recall first, then file).

## Means

| Arm | Must-file | Must-symbol | Thin n≤1 |
|-----|-----------|-------------|----------|
| map top5 (files only) | 0.863 | n/a | n/a |
| selected chunks | 0.75 | 0.679 | n/a |
| pack_context | 0.767 | 0.696 | 1/20 |
| pack_poly_embed | 0.75 | 0.696 | 1/20 |
| pack_semantic | 0.767 | 0.679 | 1/20 |

Note: pack file/symbol recall includes selected chunks ∪ pack/chain 
(agent already pasted those chunks into the pack call).

## Per case (symbol recall)

- t01 chunks=['publish_manifest', 'MemoryGovernor.demote_after_index', 'RuntimeManager.publish'] pack_context=0.25/0.5 pack_poly_embed=0.25/0.5 pack_semantic=0.25/0.5
- t02 chunks=['BM25Index', 'rebuild_bm25', 'LexicalIndex.bm25_scores'] pack_context=0.667/1.0 pack_poly_embed=0.667/1.0 pack_semantic=0.333/1.0
- t03 chunks=['chunk_file_from_ir', 'chunk_key', 'chunk_repo_from_ir'] pack_context=1.0/0.333 pack_poly_embed=1.0/0.333 pack_semantic=1.0/0.333
- t04 chunks=['repo_runtime_dir', 'gate_line_for_repo', 'managed_repo_paths'] pack_context=0.0/0.667 pack_poly_embed=0.0/0.667 pack_semantic=0.0/0.667
- t05 chunks=['is_watchdog_running', 'engine_url', 'cmd_engine'] pack_context=0.0/0.5 pack_poly_embed=0.0/0.5 pack_semantic=0.0/0.5
- t06 chunks=['McpBridge', 'McpBridge.run', 'bridge_mode'] pack_context=1.0/1.0 pack_poly_embed=1.0/1.0 pack_semantic=1.0/1.0
- t07 chunks=['cli_pack', 'cli_map', 'cmd_pack'] pack_context=0.5/1.0 pack_poly_embed=0.5/1.0 pack_semantic=0.5/1.0
- t08 chunks=['run_expand_context', 'build_call_chain', 'cli_expand'] pack_context=1.0/0.5 pack_poly_embed=1.0/0.5 pack_semantic=1.0/0.5
- t09 chunks=['touch', 'heatmap', 'RepoRuntime.touch'] pack_context=1.0/1.0 pack_poly_embed=1.0/1.0 pack_semantic=1.0/1.0
- t10 chunks=['token_mode', 'heatmap_to_cards', 'slim_locate_payload'] pack_context=1.0/0.5 pack_poly_embed=1.0/0.5 pack_semantic=1.0/0.5
- t11 chunks=['merge_cursor_permissions', 'apply_permissions_to_repo_tool_surface', 'write_cursor_mcp'] pack_context=1.0/0.5 pack_poly_embed=1.0/0.5 pack_semantic=1.0/0.5
- t12 chunks=['gate_overview_mdc', 'write_project_gate_rules', 'create_mcp'] pack_context=1.0/1.0 pack_poly_embed=1.0/1.0 pack_semantic=1.0/1.0
- t13 chunks=['BackgroundSyncLoop.sync_once', 'BackgroundSyncLoop.start', 'check_freshness'] pack_context=1.0/1.0 pack_poly_embed=1.0/1.0 pack_semantic=1.0/1.0
- t14 chunks=['embed_idle_demote_s', 'apply_index_memory_budget', 'force_apply_memory_budget'] pack_context=1.0/0.667 pack_poly_embed=1.0/0.333 pack_semantic=1.0/0.667
- t15 chunks=['build_cards', 'build_from_json', 'WarmSearchEngine.locate_capability'] pack_context=0.0/1.0 pack_poly_embed=0.0/1.0 pack_semantic=0.0/1.0
- t16 chunks=['GraphifyChunkRetriever', 'Conductor.retrieve_graphify', 'dedupe_edges'] pack_context=0.5/0.667 pack_poly_embed=0.5/0.667 pack_semantic=0.5/0.667
- t17 chunks=['never_index_repo', 'activate_repo', '_pnpm_workspace_globs'] pack_context=1.0/1.0 pack_poly_embed=1.0/1.0 pack_semantic=1.0/1.0
- t18 chunks=['wipe', 'cmd_wipe', 'remove_mcp_config'] pack_context=1.0/1.0 pack_poly_embed=1.0/1.0 pack_semantic=1.0/1.0
- t19 chunks=['cmd_dashboard', 'dashboard_status', 'cmd_status'] pack_context=1.0/1.0 pack_poly_embed=1.0/1.0 pack_semantic=1.0/1.0
- t20 chunks=['MultiArchConductor.retrieve_D_rerank', 'ConductorEngine.search', 'FaissDenseAdapter.search'] pack_context=0.0/0.5 pack_poly_embed=0.0/0.5 pack_semantic=0.0/0.5