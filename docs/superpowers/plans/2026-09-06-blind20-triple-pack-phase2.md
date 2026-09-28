# Blind-20 triple pack Phase2

Cases: **20** · Pack winner (must-file): **pack_context**

## Mean must-file recall

| Arm | Mean recall | Thin packs (n<=1) |
|-----|-------------|-------------------|
| map top5 (baseline) | 0.863 | n/a |
| pack_context | 0.537 | 15/20 |
| pack_poly_embed | 0.537 | 18/20 |
| pack_semantic | 0.537 | 15/20 |

## Per case

- t01 map=0.75 pack_context=0.25 pack_poly_embed=0.25 pack_semantic=0.25 seed=packages/pipeline/artifact_guard.py::atomic_write_text
- t02 map=1.0 pack_context=1.0 pack_poly_embed=1.0 pack_semantic=1.0 seed=packages/conductor/bm25_index.py::tokenize
- t03 map=1.0 pack_context=0.0 pack_poly_embed=0.0 pack_semantic=0.0 seed=packages/enrich/__init__.py::EnrichedChunk.to_dict
- t04 map=0.667 pack_context=0.333 pack_poly_embed=0.333 pack_semantic=0.333 seed=packages/pipeline/project_id.py::_lock_registry_file
- t05 map=0.5 pack_context=0.5 pack_poly_embed=0.5 pack_semantic=0.5 seed=packages/pipeline/watchdog.py::_home
- t06 map=1.0 pack_context=0.5 pack_poly_embed=0.5 pack_semantic=0.5 seed=packages/pipeline/mcp_bridge.py::_stderr
- t07 map=1.0 pack_context=0.5 pack_poly_embed=0.5 pack_semantic=0.5 seed=packages/pipeline/locate_cli.py::_root
- t08 map=0.5 pack_context=0.5 pack_poly_embed=0.5 pack_semantic=0.5 seed=packages/pipeline/context_trace.py::_heat
- t09 map=1.0 pack_context=1.0 pack_poly_embed=1.0 pack_semantic=1.0 seed=packages/pipeline/work_session.py::_session_path
- t10 map=1.0 pack_context=0.0 pack_poly_embed=0.0 pack_semantic=0.0 seed=packages/pipeline/session_store.py::_store_path
- t11 map=1.0 pack_context=0.5 pack_poly_embed=0.5 pack_semantic=0.5 seed=packages/pipeline/mcp_permissions.py::locate_tool_names
- t12 map=1.0 pack_context=1.0 pack_poly_embed=1.0 pack_semantic=1.0 seed=packages/pipeline/rules_installer.py::_templates_dir
- t13 map=1.0 pack_context=0.5 pack_poly_embed=0.5 pack_semantic=0.5 seed=packages/pipeline/sync_loop.py::enable_session_keeper_defaults
- t14 map=0.667 pack_context=0.333 pack_poly_embed=0.333 pack_semantic=0.333 seed=packages/pipeline/memory_governor.py::_env_float
- t15 map=1.0 pack_context=1.0 pack_poly_embed=1.0 pack_semantic=1.0 seed=packages/pipeline/capability.py::CapabilityCard.blob
- t16 map=0.667 pack_context=0.333 pack_poly_embed=0.333 pack_semantic=0.333 seed=packages/conductor/graphify_retriever.py::normalize_file
- t17 map=1.0 pack_context=1.0 pack_poly_embed=1.0 pack_semantic=1.0 seed=packages/pipeline/repo_lifecycle.py::_root
- t18 map=1.0 pack_context=0.5 pack_poly_embed=0.5 pack_semantic=0.5 seed=packages/pipeline/wipe.py::_cursor_rule_paths
- t19 map=1.0 pack_context=0.5 pack_poly_embed=0.5 pack_semantic=0.5 seed=packages/pipeline/__main__.py::_version_only
- t20 map=0.5 pack_context=0.5 pack_poly_embed=0.5 pack_semantic=0.5 seed=packages/conductor/architectures.py::_path_tokens

## Notes

- Soft map often returns file-level hits (empty symbols); enrich used map_context on seed file.
- Many packs stayed thin (n=1) when enrich-map heatmaps were tiny helpers (_root, _home, …).
- Compare pack vs map_top5: if map wins, pack expansion from weak seeds is the bottleneck.
