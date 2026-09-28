# Blind map → multi-arm pack (v2, NEW 20 queries)

Queries: `2026-09-06-blind-multipack-20-queries.json` · arms: `composite_v1`, `semantic_tracer_fuse`, `hyb_fuse_demote_noise_plus`, `poly_embed`
Elapsed pack: 13.25s · nodes: 5050 · **embed: real CodeRank DML** (≈5.2 min for 3770 new + 1280 cached)

Phase-2: `2026-09-06-blind-multipack-20-phase2.md`. Same enrich query + map seed for every arm.

| ID | Family | Seed | composite_v1 | semantic_tracer_fuse | hyb_fuse_demote_noise_plus | poly_embed |
|----|--------|------|------|------|------|------|
| `u01` | merkle-incremental | `packages/pipeline/incremental.py::incremental_sync` | hot=330 | hot=218 | hot=365 | hot=4 |
| `u02` | chunk-compress | `packages/pipeline/chunk_compress.py::compress_budget` | hot=12 | hot=12 | hot=12 | hot=5 |
| `u03` | mcp-bridge | `/pipeline/mcp_bridge_session.py::max_bridge_sessions` | hot=1 | hot=1 | hot=1 | hot=1 |
| `u04` | fair-schedule | `ages/pipeline/resources.py::ResourceManager.throttle` | hot=13 | hot=12 | hot=13 | hot=1 |
| `u05` | memory-governor | `y_governor.py::MemoryGovernor.note_embedder_unloaded` | hot=1 | hot=1 | hot=1 | hot=1 |
| `u06` | doctor-certify | `packages/pipeline/__main__.py::cmd_doctor` | hot=334 | hot=186 | hot=370 | hot=1 |
| `u07` | disconnect-tool | `packages/pipeline/__main__.py::cmd_disconnect` | hot=71 | hot=52 | hot=92 | hot=1 |
| `u08` | vector-index | `ackages/trace_lab/vector_index.py::hybrid_map_scores` | hot=9 | hot=9 | hot=9 | hot=1 |
| `u09` | recall-belt | `packages/trace_lab/recall_belt.py::bind_recall_belt` | hot=6 | hot=6 | hot=6 | hot=3 |
| `u10` | metadata-inject | `packages/enrich/__init__.py::inject_metadata` | hot=10 | hot=10 | hot=10 | hot=1 |
| `u11` | host-env-signals | `ackages/pipeline/host_workspace.py::host_env_signals` | hot=1 | hot=1 | hot=1 | hot=2 |
| `u12` | dashboard-serve | `packages/pipeline/__main__.py::cmd_dashboard` | hot=28 | hot=27 | hot=28 | hot=1 |
| `u13` | wipe-halt | `packages/pipeline/__main__.py::cmd_wipe` | hot=149 | hot=112 | hot=169 | hot=1 |
| `u14` | upgrade-flow | `packages/pipeline/__main__.py::cmd_upgrade` | hot=157 | hot=80 | hot=286 | hot=1 |
| `u15` | locate-cli-expand | `packages/pipeline/locate_cli.py::cli_expand` | hot=124 | hot=98 | hot=209 | hot=1 |
| `u16` | corpus-fingerprint | `packages/trace_lab/corpus.py::_load_cached_nodes` | hot=2 | hot=2 | hot=2 | hot=1 |
| `u17` | failure-report | `es/trace_lab/failure_report.py::build_failure_report` | hot=2 | hot=2 | hot=2 | hot=2 |
| `u18` | jedi-callgraph | `e_lab/facts/call_graph.py::build_enriched_call_graph` | hot=5 | hot=5 | hot=5 | hot=5 |
| `u19` | dfg-edges | `packages/trace_lab/facts/dfg.py::build_dfg_edges` | hot=4 | hot=4 | hot=4 | hot=1 |
| `u20` | unlock-tool | `packages/pipeline/__main__.py::cmd_unlock_tool` | hot=62 | hot=28 | hot=89 | hot=1 |

## Per case top-5

### `u01` — merkle-incremental
- seed: `packages/pipeline/incremental.py::incremental_sync` (best_in_file)
- `composite_v1`: hot=330 top5=['incremental_sync', 'root_hash', 'collect_index_paths', 'chunk_key', 'chunk_digest']
- `semantic_tracer_fuse`: hot=218 top5=['incremental_sync', 'root_hash', 'collect_index_paths', 'chunk_key', 'chunk_digest']
- `hyb_fuse_demote_noise_plus`: hot=365 top5=['incremental_sync', 'collect_index_paths', 'scan_file_hashes', 'file_sha256', 'root_hash']
- `poly_embed`: hot=4 top5=['incremental_sync', 'max_index_touch', 'AUTO_FULL_INDEX_CHUNKS', 'DEFAULT_MAX_TOUCH']

### `u02` — chunk-compress
- seed: `packages/pipeline/chunk_compress.py::compress_budget` (best_in_file)
- `composite_v1`: hot=12 top5=['compress_budget', '_pack_into', '_trim_to_budget', '_idf_weight', 'split_enriched']
- `semantic_tracer_fuse`: hot=12 top5=['compress_budget', '_pack_into', '_trim_to_budget', '_idf_weight', '_slice_budget']
- `hyb_fuse_demote_noise_plus`: hot=12 top5=['compress_budget', '_pack_into', '_slice_budget', '_trim_to_budget', '_idf_weight']
- `poly_embed`: hot=5 top5=['compress_budget', 'BUDGET_PRESETS', 'split_enriched', 'MAX_CHARS_DEFAULT', 'TARGET_SOFT']

### `u03` — mcp-bridge
- seed: `packages/pipeline/mcp_bridge_session.py::max_bridge_sessions` (best_in_file)
- `composite_v1`: hot=1 top5=['max_bridge_sessions']
- `semantic_tracer_fuse`: hot=1 top5=['max_bridge_sessions']
- `hyb_fuse_demote_noise_plus`: hot=1 top5=['max_bridge_sessions']
- `poly_embed`: hot=1 top5=['max_bridge_sessions']

### `u04` — fair-schedule
- seed: `packages/pipeline/resources.py::ResourceManager.throttle` (best_in_file)
- `composite_v1`: hot=13 top5=['ResourceManager.throttle', 'ResourceManager.sample', 'ResourceManager.budget', 'ResourceManager.wait_for_capacity', 'ResourceManager.apply_pause']
- `semantic_tracer_fuse`: hot=12 top5=['ResourceManager.throttle', 'ResourceManager.wait_for_capacity', 'ResourceManager.apply_pause', 'ResourceManager.sample', 'ResourceManager.budget']
- `hyb_fuse_demote_noise_plus`: hot=13 top5=['ResourceManager.throttle', 'ResourceManager.wait_for_capacity', 'ResourceManager.apply_pause', 'ResourceManager.budget', 'ResourceManager.sample']
- `poly_embed`: hot=1 top5=['ResourceManager.throttle']

### `u05` — memory-governor
- seed: `packages/pipeline/memory_governor.py::MemoryGovernor.note_embedder_unloaded` (best_in_file)
- `composite_v1`: hot=1 top5=['MemoryGovernor.note_embedder_unloaded']
- `semantic_tracer_fuse`: hot=1 top5=['MemoryGovernor.note_embedder_unloaded']
- `hyb_fuse_demote_noise_plus`: hot=1 top5=['MemoryGovernor.note_embedder_unloaded']
- `poly_embed`: hot=1 top5=['MemoryGovernor.note_embedder_unloaded']

### `u06` — doctor-certify
- seed: `packages/pipeline/__main__.py::cmd_doctor` (best_in_file)
- `composite_v1`: hot=334 top5=['cmd_doctor', 'apply_safe_repairs', 'doctor_repo', 'colors', 'status_line']
- `semantic_tracer_fuse`: hot=186 top5=['cmd_doctor', 'apply_safe_repairs', 'doctor_repo', 'index_is_usable', 'reconcile_git_families']
- `hyb_fuse_demote_noise_plus`: hot=370 top5=['cmd_doctor', 'doctor_repo', 'apply_safe_repairs', 'index_is_usable', 'status_line']
- `poly_embed`: hot=1 top5=['cmd_doctor']

### `u07` — disconnect-tool
- seed: `packages/pipeline/__main__.py::cmd_disconnect` (best_in_file)
- `composite_v1`: hot=71 top5=['cmd_disconnect', 'normalize_tool_slug', 'status_line', 'colors', '_ScrubGraphifyStream.write']
- `semantic_tracer_fuse`: hot=52 top5=['cmd_disconnect', 'normalize_tool_slug', 'colors', '_ScrubGraphifyStream.write', '_ScrubGraphifyStream.flush']
- `hyb_fuse_demote_noise_plus`: hot=92 top5=['cmd_disconnect', 'uninstall_tools', 'normalize_tool_slug', 'status_line', 'colors']
- `poly_embed`: hot=1 top5=['cmd_disconnect']

### `u08` — vector-index
- seed: `packages/trace_lab/vector_index.py::hybrid_map_scores` (best_in_file)
- `composite_v1`: hot=9 top5=['hybrid_map_scores', 'VectorIndex.scores', 'expand_query', 'normalize', 'tokenize']
- `semantic_tracer_fuse`: hot=9 top5=['hybrid_map_scores', 'VectorIndex.scores', 'normalize', 'expand_query', 'tokenize']
- `hyb_fuse_demote_noise_plus`: hot=9 top5=['hybrid_map_scores', 'VectorIndex.scores', 'normalize', 'expand_query', 'tokenize']
- `poly_embed`: hot=1 top5=['hybrid_map_scores']

### `u09` — recall-belt
- seed: `packages/trace_lab/recall_belt.py::bind_recall_belt` (best_in_file)
- `composite_v1`: hot=6 top5=['bind_recall_belt', 'recall_belt', 'expand_island', '_joint', '_channels']
- `semantic_tracer_fuse`: hot=6 top5=['bind_recall_belt', 'recall_belt', 'expand_island', '_joint', '_channels']
- `hyb_fuse_demote_noise_plus`: hot=6 top5=['bind_recall_belt', 'recall_belt', 'expand_island', '_joint', '_channels']
- `poly_embed`: hot=3 top5=['bind_recall_belt', 'recall_belt', 'expand_island']

### `u10` — metadata-inject
- seed: `packages/enrich/__init__.py::inject_metadata` (best_in_file)
- `composite_v1`: hot=10 top5=['inject_metadata', '_folder_name', 'build_chunk_meta', '_repo_name', '_module_name']
- `semantic_tracer_fuse`: hot=10 top5=['inject_metadata', '_folder_name', 'build_chunk_meta', '_import_labels', '_immediate_dependents']
- `hyb_fuse_demote_noise_plus`: hot=10 top5=['inject_metadata', 'build_chunk_meta', '_folder_name', '_import_labels', '_immediate_dependents']
- `poly_embed`: hot=1 top5=['inject_metadata']

### `u11` — host-env-signals
- seed: `packages/pipeline/host_workspace.py::host_env_signals` (best_in_file)
- `composite_v1`: hot=1 top5=['host_env_signals']
- `semantic_tracer_fuse`: hot=1 top5=['host_env_signals']
- `hyb_fuse_demote_noise_plus`: hot=1 top5=['host_env_signals']
- `poly_embed`: hot=2 top5=['host_env_signals', 'HOST_SPECS']

### `u12` — dashboard-serve
- seed: `packages/pipeline/__main__.py::cmd_dashboard` (best_in_file)
- `composite_v1`: hot=28 top5=['cmd_dashboard', 'dashboard_status', '_validated_dashboard_state', '_clear_stale_state', '_pid_alive']
- `semantic_tracer_fuse`: hot=27 top5=['cmd_dashboard', 'dashboard_status', '_validated_dashboard_state', '_clear_stale_state', '_pid_alive']
- `hyb_fuse_demote_noise_plus`: hot=28 top5=['cmd_dashboard', 'dashboard_status', '_clear_stale_state', '_validated_dashboard_state', 'print_dashboard_summary']
- `poly_embed`: hot=1 top5=['cmd_dashboard']

### `u13` — wipe-halt
- seed: `packages/pipeline/__main__.py::cmd_wipe` (best_in_file)
- `composite_v1`: hot=149 top5=['cmd_wipe', 'warn', 'colors', '_ScrubGraphifyStream.write', '_ScrubGraphifyStream.flush']
- `semantic_tracer_fuse`: hot=112 top5=['cmd_wipe', 'colors', '_ScrubGraphifyStream.write', '_ScrubGraphifyStream.flush', 'status_line']
- `hyb_fuse_demote_noise_plus`: hot=169 top5=['cmd_wipe', 'wipe', 'wipe_repo', 'status_line', 'colors']
- `poly_embed`: hot=1 top5=['cmd_wipe']

### `u14` — upgrade-flow
- seed: `packages/pipeline/__main__.py::cmd_upgrade` (best_in_file)
- `composite_v1`: hot=157 top5=['cmd_upgrade', 'check_pypi_version', 'installed_version', 'status_line', 'platform_name']
- `semantic_tracer_fuse`: hot=80 top5=['cmd_upgrade', 'check_pypi_version', 'installed_version', 'platform_name', 'context_engine_home']
- `hyb_fuse_demote_noise_plus`: hot=286 top5=['cmd_upgrade', 'check_pypi_version', 'installed_version', 'do_upgrade', '_save_update_check']
- `poly_embed`: hot=1 top5=['cmd_upgrade']

### `u15` — locate-cli-expand
- seed: `packages/pipeline/locate_cli.py::cli_expand` (best_in_file)
- `composite_v1`: hot=124 top5=['cli_expand', '_load_repo', 'iter_python_files', 'rel_posix', '_make_id']
- `semantic_tracer_fuse`: hot=98 top5=['cli_expand', 'tokenize', '_norm_path', '_root', 'run_expand_context']
- `hyb_fuse_demote_noise_plus`: hot=209 top5=['cli_expand', 'run_expand_context', '_root', '_load_repo', '_norm_path']
- `poly_embed`: hot=1 top5=['cli_expand']

### `u16` — corpus-fingerprint
- seed: `packages/trace_lab/corpus.py::_load_cached_nodes` (best_in_file)
- `composite_v1`: hot=2 top5=['_load_cached_nodes', '_cache_path']
- `semantic_tracer_fuse`: hot=2 top5=['_load_cached_nodes', '_cache_path']
- `hyb_fuse_demote_noise_plus`: hot=2 top5=['_load_cached_nodes', '_cache_path']
- `poly_embed`: hot=1 top5=['_load_cached_nodes']

### `u17` — failure-report
- seed: `packages/trace_lab/failure_report.py::build_failure_report` (best_in_file)
- `composite_v1`: hot=2 top5=['build_failure_report', 'classify_miss']
- `semantic_tracer_fuse`: hot=2 top5=['build_failure_report', 'classify_miss']
- `hyb_fuse_demote_noise_plus`: hot=2 top5=['build_failure_report', 'classify_miss']
- `poly_embed`: hot=2 top5=['build_failure_report', 'classify_miss']

### `u18` — jedi-callgraph
- seed: `packages/trace_lab/facts/call_graph.py::build_enriched_call_graph` (best_in_file)
- `composite_v1`: hot=5 top5=['build_enriched_call_graph', 'merge_call_edges', 'edges_from_ast', 'edges_from_dispatch', 'edges_from_jedi']
- `semantic_tracer_fuse`: hot=5 top5=['build_enriched_call_graph', 'edges_from_jedi', 'edges_from_dispatch', 'merge_call_edges', 'edges_from_ast']
- `hyb_fuse_demote_noise_plus`: hot=5 top5=['build_enriched_call_graph', 'edges_from_jedi', 'edges_from_dispatch', 'merge_call_edges', 'edges_from_ast']
- `poly_embed`: hot=5 top5=['build_enriched_call_graph', 'edges_from_ast', 'merge_call_edges', 'edges_from_jedi', 'edges_from_dispatch']

### `u19` — dfg-edges
- seed: `packages/trace_lab/facts/dfg.py::build_dfg_edges` (best_in_file)
- `composite_v1`: hot=4 top5=['build_dfg_edges', '_parse', 'iter_python_files', 'rel_posix']
- `semantic_tracer_fuse`: hot=4 top5=['build_dfg_edges', '_parse', 'iter_python_files', 'rel_posix']
- `hyb_fuse_demote_noise_plus`: hot=4 top5=['build_dfg_edges', '_parse', 'iter_python_files', 'rel_posix']
- `poly_embed`: hot=1 top5=['build_dfg_edges']

### `u20` — unlock-tool
- seed: `packages/pipeline/__main__.py::cmd_unlock_tool` (best_in_file)
- `composite_v1`: hot=62 top5=['cmd_unlock_tool', 'status_line', 'unlock_uv_tool_env', 'success', 'warn']
- `semantic_tracer_fuse`: hot=28 top5=['cmd_unlock_tool', 'unlock_uv_tool_env', 'success', 'warn', 'prepare_uv_tool_directory_for_swap']
- `hyb_fuse_demote_noise_plus`: hot=89 top5=['cmd_unlock_tool', 'unlock_uv_tool_env', 'success', 'prepare_uv_tool_directory_for_swap', 'status_line']
- `poly_embed`: hot=1 top5=['cmd_unlock_tool']

