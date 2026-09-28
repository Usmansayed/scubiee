# Blind multipack phase-2 (NEW 20 · 4 arms)

Winner by pack must-symbol then must-file: **`semantic_tracer_fuse`** (tied recall with composite/hyb; tighter mean hot).

Embed: **real CodeRank DML** batch=16 (3770 new + 1280 cached ≈ 5.2 min). NEW u01–u20.

Shared map seeds across arms. Score = coverage of independent must files/symbols in pack top15∪hot.

| Arm | Pack must-file | Pack must-sym | Union must-file | Mean hot | Thin≤3 |
|-----|----------------|---------------|-----------------|----------|--------|
| `semantic_tracer_fuse` | 0.850 | 0.575 | 0.975 | 43.3 | 5/20 |
| `composite_v1` | 0.850 | 0.575 | 0.975 | 66.0 | 5/20 |
| `hyb_fuse_demote_noise_plus` | 0.850 | 0.575 | 0.975 | 83.7 | 5/20 |
| `poly_embed` | 0.775 | 0.575 | 0.950 | 1.8 | 17/20 |

Map must-file (shared): 0.950 · seed in must-files: 1.000

## Per case (winner vs composite)

### `u01` seed=`packages/pipeline/incremental.py::incremental_sync`
- `composite_v1`: file=1.00 sym=0.50 hot=330 miss_sym=['packages/pipeline/chunk_merkle.py::diff_chunk_records']
- `semantic_tracer_fuse`: file=1.00 sym=0.50 hot=218 miss_sym=['packages/pipeline/chunk_merkle.py::diff_chunk_records']

### `u02` seed=`packages/pipeline/chunk_compress.py::compress_budget`
- `composite_v1`: file=1.00 sym=0.00 hot=12 miss_sym=['packages/pipeline/chunk_compress.py::compress_chunk', 'packages/pipeline/chunk_compress.py::resolve_compress_mode']
- `semantic_tracer_fuse`: file=1.00 sym=0.00 hot=12 miss_sym=['packages/pipeline/chunk_compress.py::compress_chunk', 'packages/pipeline/chunk_compress.py::resolve_compress_mode']

### `u03` seed=`packages/pipeline/mcp_bridge_session.py::max_bridge_sessions`
- `composite_v1`: file=0.50 sym=0.00 hot=1 miss_sym=['packages/pipeline/mcp_bridge_session.py::ChildWorker._child_env', 'packages/pipeline/mcp_bridge_session.py::SessionRegistry']
- `semantic_tracer_fuse`: file=0.50 sym=0.00 hot=1 miss_sym=['packages/pipeline/mcp_bridge_session.py::ChildWorker._child_env', 'packages/pipeline/mcp_bridge_session.py::SessionRegistry']

### `u04` seed=`packages/pipeline/resources.py::ResourceManager.throttle`
- `composite_v1`: file=1.00 sym=0.50 hot=13 miss_sym=['packages/pipeline/resources.py::ResourceManager.run_job']
- `semantic_tracer_fuse`: file=1.00 sym=0.50 hot=12 miss_sym=['packages/pipeline/resources.py::ResourceManager.run_job']

### `u05` seed=`packages/pipeline/memory_governor.py::MemoryGovernor.note_embedder_unloaded`
- `composite_v1`: file=1.00 sym=0.00 hot=1 miss_sym=['packages/pipeline/memory_governor.py::MemoryGovernor.maybe_demote_idle', 'packages/pipeline/memory_governor.py::MemoryGovernor.apply_tier']
- `semantic_tracer_fuse`: file=1.00 sym=0.00 hot=1 miss_sym=['packages/pipeline/memory_governor.py::MemoryGovernor.maybe_demote_idle', 'packages/pipeline/memory_governor.py::MemoryGovernor.apply_tier']

### `u06` seed=`packages/pipeline/__main__.py::cmd_doctor`
- `composite_v1`: file=0.50 sym=0.50 hot=334 miss_sym=['packages/pipeline/__main__.py::cmd_certify']
- `semantic_tracer_fuse`: file=0.50 sym=0.50 hot=186 miss_sym=['packages/pipeline/__main__.py::cmd_certify']

### `u07` seed=`packages/pipeline/__main__.py::cmd_disconnect`
- `composite_v1`: file=1.00 sym=1.00 hot=71 miss_sym=[]
- `semantic_tracer_fuse`: file=1.00 sym=1.00 hot=52 miss_sym=[]

### `u08` seed=`packages/trace_lab/vector_index.py::hybrid_map_scores`
- `composite_v1`: file=1.00 sym=0.50 hot=9 miss_sym=['packages/trace_lab/vector_index.py::VectorIndex']
- `semantic_tracer_fuse`: file=1.00 sym=0.50 hot=9 miss_sym=['packages/trace_lab/vector_index.py::VectorIndex']

### `u09` seed=`packages/trace_lab/recall_belt.py::bind_recall_belt`
- `composite_v1`: file=1.00 sym=0.50 hot=6 miss_sym=['packages/trace_lab/recall_belt.py::recall_fuse']
- `semantic_tracer_fuse`: file=1.00 sym=0.50 hot=6 miss_sym=['packages/trace_lab/recall_belt.py::recall_fuse']

### `u10` seed=`packages/enrich/__init__.py::inject_metadata`
- `composite_v1`: file=1.00 sym=0.50 hot=10 miss_sym=['packages/enrich/__init__.py::enrich_repo']
- `semantic_tracer_fuse`: file=1.00 sym=0.50 hot=10 miss_sym=['packages/enrich/__init__.py::enrich_repo']

### `u11` seed=`packages/pipeline/host_workspace.py::host_env_signals`
- `composite_v1`: file=1.00 sym=1.00 hot=1 miss_sym=[]
- `semantic_tracer_fuse`: file=1.00 sym=1.00 hot=1 miss_sym=[]

### `u12` seed=`packages/pipeline/__main__.py::cmd_dashboard`
- `composite_v1`: file=1.00 sym=0.50 hot=28 miss_sym=['packages/pipeline/__main__.py::cmd_serve']
- `semantic_tracer_fuse`: file=1.00 sym=0.50 hot=27 miss_sym=['packages/pipeline/__main__.py::cmd_serve']

### `u13` seed=`packages/pipeline/__main__.py::cmd_wipe`
- `composite_v1`: file=1.00 sym=0.50 hot=149 miss_sym=['packages/pipeline/__main__.py::cmd_halt']
- `semantic_tracer_fuse`: file=1.00 sym=0.50 hot=112 miss_sym=['packages/pipeline/__main__.py::cmd_halt']

### `u14` seed=`packages/pipeline/__main__.py::cmd_upgrade`
- `composite_v1`: file=1.00 sym=1.00 hot=157 miss_sym=[]
- `semantic_tracer_fuse`: file=1.00 sym=1.00 hot=80 miss_sym=[]

### `u15` seed=`packages/pipeline/locate_cli.py::cli_expand`
- `composite_v1`: file=0.50 sym=0.50 hot=124 miss_sym=['packages/pipeline/__main__.py::cmd_expand']
- `semantic_tracer_fuse`: file=0.50 sym=0.50 hot=98 miss_sym=['packages/pipeline/__main__.py::cmd_expand']

### `u16` seed=`packages/trace_lab/corpus.py::_load_cached_nodes`
- `composite_v1`: file=0.50 sym=0.00 hot=2 miss_sym=['packages/trace_lab/corpus.py::corpus_fingerprint', 'packages/trace_lab/corpus.py::extract_nodes']
- `semantic_tracer_fuse`: file=0.50 sym=0.00 hot=2 miss_sym=['packages/trace_lab/corpus.py::corpus_fingerprint', 'packages/trace_lab/corpus.py::extract_nodes']

### `u17` seed=`packages/trace_lab/failure_report.py::build_failure_report`
- `composite_v1`: file=1.00 sym=1.00 hot=2 miss_sym=[]
- `semantic_tracer_fuse`: file=1.00 sym=1.00 hot=2 miss_sym=[]

### `u18` seed=`packages/trace_lab/facts/call_graph.py::build_enriched_call_graph`
- `composite_v1`: file=0.50 sym=1.00 hot=5 miss_sym=[]
- `semantic_tracer_fuse`: file=0.50 sym=1.00 hot=5 miss_sym=[]

### `u19` seed=`packages/trace_lab/facts/dfg.py::build_dfg_edges`
- `composite_v1`: file=0.50 sym=1.00 hot=4 miss_sym=[]
- `semantic_tracer_fuse`: file=0.50 sym=1.00 hot=4 miss_sym=[]

### `u20` seed=`packages/pipeline/__main__.py::cmd_unlock_tool`
- `composite_v1`: file=1.00 sym=1.00 hot=62 miss_sym=[]
- `semantic_tracer_fuse`: file=1.00 sym=1.00 hot=28 miss_sym=[]

