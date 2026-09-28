# Blind map→pack 20 (no correctness eval)

Elapsed 209.16s · map_ok 20/20 · pack_ok 20/20

Phase 1 only: enrich query → map seed → pack. Ground-truth comparison is deferred.

| ID | Family | Map | Pack | Seed | n_pack |
|----|--------|-----|------|------|--------|
| `t01` | session-isolation | True | True | `packages/pipeline/session_store.py::` | 4 |
| `t02` | install-cursor-surface | True | True | `packages/pipeline/rules_installer.py::` | 1 |
| `t03` | map-pack-ladder | True | True | `packages/pipeline/context_trace.py::` | 1 |
| `t04` | composite-tracer | True | True | `packages/trace_lab/composite_v1.py::` | 4 |
| `t05` | embed-filter-noise | True | True | `packages/trace_lab/poly_embed.py::` | 4 |
| `t06` | semantic-comparator | True | True | `packages/trace_lab/semantic_tracer_fuse.py::` | 1 |
| `t07` | cli-pack | True | True | `packages/trace_lab/policy/faction.py::` | 3 |
| `t08` | index-publish | True | True | `packages/pipeline/artifact_guard.py::` | 4 |
| `t09` | embed-backend | True | True | `packages/pipeline/embedder.py::` | 1 |
| `t10` | gate-rules | True | True | `packages/pipeline/rules_installer.py::` | 1 |
| `t11` | mcp-tool-schema | True | True | `packages/pipeline/mcp_locate.py::` | 1 |
| `t12` | expand-hop | True | True | `packages/pipeline/context_trace.py::` | 1 |
| `t13` | permissions-allowlist | True | True | `packages/pipeline/rules_installer.py::` | 1 |
| `t14` | graphify-ast | True | True | `packages/trace_lab/graphify_layer.py::` | 1 |
| `t15` | lsp-dispatch | True | True | `packages/trace_lab/lsp_index.py::` | 4 |
| `t16` | session-store-files | True | True | `packages/pipeline/session_store.py::` | 4 |
| `t17` | status-health | True | True | `packages/pipeline/__init__.py::` | 1 |
| `t18` | teleport-ablation | True | True | `packages/trace_lab/semantic_tracer_fuse.py::` | 1 |
| `t19` | prod-eval-enrich | True | True | `packages/trace_lab/prod_eval.py::` | 1 |
| `t20` | hybrid-register | True | True | `packages/trace_lab/strategies.py::` | 1 |

## Queries + seeds

### `t01` — session-isolation

- Task: Fix a bug where two parallel agent chats share recall/pins in one MCP process.
- Enrich query: `session isolation require_session_id fail closed MCP shared process bucket session_store put_span work_session rematerialize pins recall per connection CTX_MCP_SESSION_ID`
- Seed (suggested_seed): `packages/pipeline/session_store.py::`
- Pack bodies: 4 · ids: packages/pipeline/session_store.py::_store_path, packages/pipeline/project_id.py::repo_runtime_dir, packages/pipeline/session_isolation.py::effective_session_id, packages/pipeline/session_isolation.py::_session_isolate_enabled

### `t02` — install-cursor-surface

- Task: Understand how scubiee connect wires Cursor mcp.json autoApprove and project permissions.
- Enrich query: `scubiee connect install_tool write_project_tool_surface apply_permissions_to_repo_tool_surface Cursor mcp.json autoApprove permissions.json mcpAllowlist write_project_gate_rules AGENTS.md GATE`
- Seed (suggested_seed): `packages/pipeline/rules_installer.py::`
- Pack bodies: 1 · ids: packages/pipeline/rules_installer.py::_templates_dir

### `t03` — map-pack-ladder

- Task: Explain how map suggests a seed and pack builds the lean heatmap with bodies.
- Enrich query: `map_context suggested_seed pack_context mode lean heatmap chain hot bodies cards loc rank expand_context collect_hot_context locate ladder`
- Seed (suggested_seed): `packages/pipeline/context_trace.py::`
- Pack bodies: 1 · ids: packages/pipeline/context_trace.py::_heat

### `t04` — composite-tracer

- Task: Where does composite_v1 decide membership then rank heat with DFG boost?
- Enrich query: `composite_v1 membership edges best_first expand apply_rank_composite DFG PASSES_DATA_TO sink demotion poly foreign slice_mask trace_lab`
- Seed (suggested_seed): `packages/trace_lab/composite_v1.py::`
- Pack bodies: 4 · ids: packages/trace_lab/composite_v1.py::_membership_edges, packages/conductor/bm25_index.py::tokenize, packages/trace_lab/policy/slice_mask.py::short_name, packages/trace_lab/polytrace.py::faction_of

### `t05` — embed-filter-noise

- Task: How do we demote logger/analytics noise on a structural island without dropping bridges?
- Enrich query: `apply_embed_keep_drop demote_noise_plus SITE_EFFECTS bridge names path preserve hot_floor EmbedField affinities poly_embed hybrid`
- Seed (suggested_seed): `packages/trace_lab/poly_embed.py::`
- Pack bodies: 4 · ids: packages/trace_lab/poly_embed.py::poly_embed_trace, packages/trace_lab/polytrace.py::faction_of, packages/trace_lab/polytrace.py::is_foreign, packages/trace_lab/retrieve.py::query_intent

### `t06` — semantic-comparator

- Task: How does the semantic tracer use query/seed embeddings as edge expansion priority?
- Enrich query: `SemanticComparator semantic_best_first_expand query seed affinity trace centroid refresh hub_penalty semantic_tracer_fuse edge_sim`
- Seed (suggested_seed): `packages/trace_lab/semantic_tracer_fuse.py::`
- Pack bodies: 1 · ids: packages/trace_lab/semantic_tracer_fuse.py::_graph_degree

### `t07` — cli-pack

- Task: Implement or debug the scubiee pack CLI flag path for seed-file and lean mode.
- Enrich query: `scubiee pack CLI argparse seed-file seed-symbol mode lean full policy strict broad pack_context command entry`
- Seed (suggested_seed): `packages/trace_lab/policy/faction.py::`
- Pack bodies: 3 · ids: packages/trace_lab/policy/faction.py::is_foreign_node, packages/conductor/bm25_index.py::tokenize, packages/trace_lab/polytrace.py::faction_of

### `t08` — index-publish

- Task: Index publication missing or checksum invalid — find refuse-mixed-generation and republish path.
- Enrich query: `Index publication missing checksum-invalid refusing mixed generation publish merkle chunks sync init scubiee index`
- Seed (suggested_seed): `packages/pipeline/artifact_guard.py::`
- Pack bodies: 4 · ids: packages/pipeline/artifact_guard.py::atomic_write_text, packages/pipeline/artifact_guard.py::_atomic_write_text_unlocked, packages/pipeline/store_lock.py::store_write_lock, packages/pipeline/artifact_guard.py::_atomic_replace

### `t09` — embed-backend

- Task: How does embedding choose DirectML vs CUDA vs CPU and cache coderank vectors?
- Enrich query: `EmbedField FastEmbed CodeRankEmbed DmlExecutionProvider CUDA cache coderank.jsonl batch providers embedder progress`
- Seed (suggested_seed): `packages/pipeline/embedder.py::`
- Pack bodies: 1 · ids: packages/pipeline/embedder.py::text_key

### `t10` — gate-rules

- Task: Where is the managed-repo GATE text written into AGENTS.md and steering files?
- Enrich query: `write_project_gate_rules GATE 1 project_id AGENTS.md scubiee.md steering managed enroll`
- Seed (suggested_seed): `packages/pipeline/rules_installer.py::`
- Pack bodies: 1 · ids: packages/pipeline/rules_installer.py::_templates_dir

### `t11` — mcp-tool-schema

- Task: Add or inspect MCP tool registration for pack_context and map_context schemas.
- Enrich query: `pack_context map_context MCP tool register FastMCP server instructions hybrid experiment CTX_MCP_EXPERIMENT`
- Seed (suggested_seed): `packages/pipeline/mcp_locate.py::`
- Pack bodies: 1 · ids: packages/pipeline/mcp_locate.py::_active_surface

### `t12` — expand-hop

- Task: Missing callee hop after pack — how does expand_context direction callees with bodies work?
- Enrich query: `expand_context direction callees callers effects broad with_bodies node id delta collect_hot_context`
- Seed (suggested_seed): `packages/pipeline/context_trace.py::`
- Pack bodies: 1 · ids: packages/pipeline/context_trace.py::_heat

### `t13` — permissions-allowlist

- Task: Debug mcp-permissions.json allowlist merge when installing a host tool surface.
- Enrich query: `mcp-permissions.json mcpAllowlist apply_permissions write_project_tool_surface install permissions merge allowlist`
- Seed (suggested_seed): `packages/pipeline/rules_installer.py::`
- Pack bodies: 1 · ids: packages/pipeline/rules_installer.py::_templates_dir

### `t14` — graphify-ast

- Task: How does graphify AST graph get built and fed into polytrace / composite edges?
- Enrich query: `graphify build_graphify_graph AstTraceGraph polytrace compose_pdg edges_from_graphify call graph`
- Seed (suggested_seed): `packages/trace_lab/graphify_layer.py::`
- Pack bodies: 1 · ids: packages/trace_lab/graphify_layer.py::_map_symbol

### `t15` — lsp-dispatch

- Task: Where do LSP dispatch and override edges affect polytrace keep/drop for handlers?
- Enrich query: `LspIndex dispatch overrides build_lsp_index polytrace used_by handle lookup registry`
- Seed (suggested_seed): `packages/trace_lab/lsp_index.py::`
- Pack bodies: 4 · ids: packages/trace_lab/lsp_index.py::build_lsp_index, packages/trace_lab/ast_graph.py::_call_name, packages/trace_lab/lsp_index.py::_uniq_lists, packages/trace_lab/lsp_index.py::_collect_inheritance

### `t16` — session-store-files

- Task: Trace persistence of session_store.json and work_session.json under .scubiee/sessions.
- Enrich query: `session_store.json work_session.json .scubiee/sessions put_span lock rematerialize persist bucket`
- Seed (suggested_seed): `packages/pipeline/session_store.py::`
- Pack bodies: 4 · ids: packages/pipeline/session_store.py::_store_path, packages/pipeline/project_id.py::repo_runtime_dir, packages/pipeline/session_isolation.py::effective_session_id, packages/pipeline/session_isolation.py::_session_isolate_enabled

### `t17` — status-health

- Task: What does scubiee status / gate report for managed health vs locate readiness?
- Enrich query: `scubiee status gate managed health ok chunks merkle engine server project_id enroll`
- Seed (suggested_seed): `packages/pipeline/__init__.py::`
- Pack bodies: 1 · ids: packages/pipeline/__init__.py::__getattr__

### `t18` — teleport-ablation

- Task: Why was strict embed teleport left off by default in semantic_tracer_fuse?
- Enrich query: `apply_strict_embed_teleport with_teleport semantic_tracer_fuse min_sem hub_penalty FN recovery must_not`
- Seed (suggested_seed): `packages/trace_lab/semantic_tracer_fuse.py::`
- Pack bodies: 1 · ids: packages/trace_lab/semantic_tracer_fuse.py::_graph_degree

### `t19` — prod-eval-enrich

- Task: How does production-like verify enrich a paragraph with two seed code chunks?
- Enrich query: `_enrich_query Seed code anchors seed_chunks multi-seed merge_heatmaps prod_eval verify_prod`
- Seed (suggested_seed): `packages/trace_lab/prod_eval.py::`
- Pack bodies: 1 · ids: packages/trace_lab/prod_eval.py::_enrich_query

### `t20` — hybrid-register

- Task: Where are hybrid combo arms registered into compile_bundle with_embed_power?
- Enrich query: `register_hybrid_arms HYBRID_SPECS hyb_fuse_demote_noise_plus compile_bundle with_embed_power strategies bind_hybrid_filter`
- Seed (suggested_seed): `packages/trace_lab/strategies.py::`
- Pack bodies: 1 · ids: packages/trace_lab/strategies.py::_seed_id

