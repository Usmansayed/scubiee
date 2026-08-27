# Scubiee Internals: Architecture and Operations

> Product name: **Scubiee**. CLI / `mcp.json` key: **`scubiee`**.  
> On-disk data: **`~/.scubiee/`** and **`<repo>/.scubiee/`** (no legacy `.context-engine` path).  
> "CE" below is optional engineering shorthand for the Scubiee engine only.

> **Implementation baseline:** Scubiee `0.2.87`  
> **Audience:** engineers, operators, integration authors, and maintainers building the technical sections of a documentation website.

This document describes the current Scubiee architecture rather than the historical research prototypes. The public command and product guide is in [`commands-and-setup.md`](./commands-and-setup.md).

## System purpose

Scubiee is a local repository-context service with three faces:

1. **CLI:** setup, registration, indexing, lifecycle, search, diagnostics, and operator control.
2. **Daemon/runtime:** a local HTTP service that owns repository runtimes, index freshness, resources, and background lifecycle.
3. **MCP adapter:** a thin client-facing process that exposes repository discovery tools and forwards work to the daemon.

The central contract is: a coding tool may use Scubiee discovery when the current repository is known, managed, and healthy; otherwise it must fall back to its native tools without treating Scubiee as mandatory.

## Architecture at a glance

```text
+----------------------+       +--------------------------+
| AI coding tool       |       | scubiee CLI                  |
| global rule + MCP    |       | setup/init/search/status  |
+----------+-----------+       +------------+-------------+
           |                                 |
           v                                 v
+----------------------------------------------------------+
| mcp_locate.py / EngineClient / CLI client boundary       |
| status gate, repo selection, surface selection           |
+------------------------------+---------------------------+
                               | local HTTP
                               v
+----------------------------------------------------------+
| daemon.py + server.py + RuntimeManager                  |
| RepoHub -> RepoRuntime -> IndexManager + ResourceManager |
| lifecycle standby/idle/autostart + watchdog              |
+------------------------------+---------------------------+
                               |
                +--------------+--------------+
                |                             |
                v                             v
+---------------------------+       +-------------------------+
| Registration and identity |       | Index/search data plane  |
| repo_lifecycle.py         |       | scan -> graph -> chunks |
| project_id.py             |       | -> embed -> vector      |
| git_family.py             |       | -> retrieve/fuse        |
+-------------+-------------+       +------------+------------+
              |                                  |
              v                                  v
       .scubiee/id.json       project store + vectordb
       registry/prefs                chunks/Merkle/meta/manifest
```

The control plane decides whether a repository is eligible and which runtime owns it. The data plane produces and serves search artifacts. Keeping those concerns separate prevents an unregistered or ambiguous repository from being silently indexed or served by the wrong daemon.

## Component ownership

| Area | Primary modules | Responsibility |
| --- | --- | --- |
| CLI and command dispatch | `packages/pipeline/__main__.py` | Defines the `scubiee` command surface and connects commands to setup, lifecycle, search, daemon, diagnostics, connect/disconnect, and wipe handlers. |
| Hardware/provider setup | `accel.py`, `runtime_profile.py`, `embedder.py`, `preflight.py` | Detects capabilities, selects an execution profile, installs/validates the runtime, prepares CodeRankEmbed, and fails closed when required capabilities are not available. |
| Registration/lifecycle | `repo_lifecycle.py`, `settings.py` | Applies enrollment, consent/registration policy, activation, pause/resume, sync, rebuild, removal, and persistent never-index decisions. |
| Project identity | `project_id.py`, `git_family.py` | Resolves a stable `ce_...` project ID and reconciles duplicate/moved repositories, Git common directories, and linked worktrees. |
| Full indexing | `indexer.py` | Orchestrates admission, capability checks, Merkle scan, Graphify parsing, graph/chunk construction, embedding, vector persistence, and artifact publication. |
| Incremental indexing | `incremental.py`, `sync_loop.py` | Detects dirty files, reparses and rechunks only affected content, embeds changed/new chunks, publishes a new generation, and escalates oversized changes to a full rebuild. |
| Retrieval | `ce_service.py`, search/retrieval components | Warms search state, computes lexical/dense/graph signals, fuses candidates, and expands context around high-value results. |
| Runtime and daemon | `daemon.py`, `server.py`, `lifecycle_runtime.py` | Owns HTTP serving, repository runtime routing, idle/standby behavior, autostart, and runtime coordination. |
| Resource control | `ResourceManager` and setup/runtime resource components | Tracks hardware pressure and controls adaptive budgets for indexing and retrieval. |
| Watchdog | `watchdog.py` | Monitors the managed runtime and can wake/restart/reconcile it according to watchdog policy. |
| MCP surface | `mcp_locate.py` | Selects the MCP surface, exposes tools, checks managed status, applies server instructions, and forwards requests to the daemon. |
| MCP installation | `mcp_install.py`, `tool_registry.py`, `rules_installer.py` | Produces client-specific MCP entries, config paths, global rule/instruction files, and handles `connect`/`disconnect` operations. |
| Vector storage | `vectordb.py`, TurboQuant/FAISS components | Stores compressed embeddings and vector catalogs under the Scubiee data root. |
| Path/scope policy | `paths.py`, `storage_policy.py` | Resolves fast roots, artifact layout, compaction and persistence policy, and storage safety constraints. |

## Lifecycle: setup, registration, indexing

### Machine setup

`scubiee setup` is the machine-level path. In broad terms it:

1. snapshots hardware and available accelerators;
2. selects or validates a runtime profile (`cuda`, `dml`, `mlx`, `coreml`, or `cpu`);
3. installs or repairs the appropriate runtime unless skipped;
4. prepares and warms the `nomic-ai/CodeRankEmbed` model unless skipped;
5. benchmarks/calibrates local batch and resource settings unless skipped;
6. installs the runtime/supervisor behavior used by the local daemon; and
7. writes or refreshes MCP defaults and optional repository registration/indexing requested by setup flags.

Provider and capability failures are not treated as successful setup. The operator can select CPU explicitly rather than receiving a silently degraded or partially configured indexer.

### Repository enrollment

`scubiee init PATH` is the normal repository-facing path:

1. normalize and validate the repository root;
2. apply registration and consent policy;
3. resolve/reconcile a stable project identity;
4. record the repository in trusted registry/state;
5. create or reuse a repository runtime/store;
6. index unless `--no-index` was supplied; and
7. ensure that the daemon can serve the repository.

`scubiee register PATH` is the explicit registration variant. `scubiee initialize PATH` is the lifecycle-oriented entry point used when initializing or reconciling a managed repository. These operations are intentionally distinct from `scubiee setup`, so adding another repository does not repeat machine provider installation.

### Full index sequence

The full index pipeline is an ordered publication process:

```text
repository admission
  -> capability/provider validation
  -> Merkle scan and diff baseline
  -> Graphify parsing and RepoIR
  -> graph construction
  -> symbol/file chunk generation
  -> metadata enrichment and compression
  -> CodeRankEmbed embeddings
  -> FAISS/TurboQuant vector write
  -> chunks + Merkle + metadata + manifest publication
```

Each phase has a different failure boundary. Admission and capability checks happen before expensive work. Parsing produces structural information used by both chunks and graph affinity. Embedding is performed only after the chunk set is known. Vector and metadata artifacts are then published as a coherent index generation for retrieval.

## Data model: chunks, graph, vectors, and artifacts

### Repository and project identity

A repository is not identified only by its current absolute path. Scubiee records evidence from:

- the in-repository `.scubiee/id.json`;
- the trusted user registry;
- the per-project store;
- the Git common directory and worktree family; and
- the current repository path and Git metadata.

`project_id.resolve_project` scores the available evidence and mints a new `ce_...` ID only when an existing identity cannot be trusted. `git_family.reconcile_git_families` repairs duplicate or conflicting IDs across a Git root and its linked worktrees.

### Chunks

Index content is represented as symbol- and file-oriented chunks enriched with repository-relative paths and structural metadata. Chunk metadata is used to:

- filter and explain retrieval results;
- connect a hit to its file, symbol, and graph neighborhood;
- support targeted incremental replacement; and
- keep the published generation aligned with the Merkle state.

The index is not just a bag of fixed-size text windows. Graphify/RepoIR structure gives the system symbols and relationships that can be used during retrieval and expansion.

### Graph

The graph captures structural affinity produced from parsed repository information. It complements text and embedding similarity: a result can become more useful when it is connected to callers, callees, imports, definitions, or other structurally related context represented by the parser/graph layer.

### Vectors

CodeRankEmbed converts chunks into dense vectors. FAISS provides approximate nearest-neighbor retrieval, while TurboQuant/compressed storage controls the memory and persistence cost. The vector catalog and per-project store are kept under the local Scubiee data root.

### Published artifacts

A generation contains the data needed to align retrieval with repository state, including chunk data, Merkle state, metadata, manifest information, and vector artifacts. Incremental updates publish a new generation after changed content is reparsed and embedded; readers should use the published generation rather than partial intermediate files.

## Retrieval path

The production retrieval path is built around a warm search engine and a multi-signal ranking flow:

```text
query
  -> capability/search readiness cards
  -> BM25 / lexical candidates
  -> dense FAISS candidates
  -> Graphify structural affinity
  -> RRF or min-rank fusion
  -> graph/context expansion
  -> final context hits
```

The production multi-architecture path uses `MultiArchConductor.retrieve_D_channel_best`. The exact implementation may choose a local or daemon-backed route, but the behavioral contract is the same: lexical evidence, semantic evidence, and repository structure are fused rather than relying on one ranking signal.

`WarmSearchEngine` is the readiness boundary for retrieval. A cold or unavailable dense index can be surfaced through status/capability information instead of being mistaken for a healthy semantic search result. CLI `scubiee search` can use the warm server path, a local path (`--local`), or an explicit `--url`.

## Incremental and live re-indexing

The incremental path is owned by `incremental.py` and coordinated by `sync_loop.py`:

1. detect dirty files since the last published state;
2. compare the file set and content against Merkle state;
3. reparse only changed/new files;
4. remove or replace affected chunks and graph metadata;
5. embed changed/new chunks;
6. update vector and metadata state; and
7. publish the next consistent generation.

The live loop includes debounce and bulk-change controls. Current guard defaults include:

- `CTX_LIVE_MAX_FILES=200`;
- `CTX_LIVE_MAX_CHUNKS=300`;
- `CTX_INCREMENTAL_MAX_TOUCH=200`;
- `CTX_AUTO_FULL_INDEX_CHUNKS=10000`;
- `CTX_BULK_REINDEX_THRESHOLD=300`;
- `CTX_CHANGE_POLL_MS=1000`; and
- `CTX_SYNC_INTERVAL_MS=300000` for the normal five-minute background interval.

These are operational defaults, not promises that every repository will use the same workload. A change set that is too large or too structurally disruptive is escalated to a full index so that incremental mutation does not produce an unsafe or incomplete graph/vector state. An explicit `scubiee init --confirm` bypasses the 200-file incremental touch confirmation, while the chunk safety limit and provider/resource guards still apply.

## Runtime, daemon, and watchdog

### Runtime ownership

The daemon hosts a `RuntimeManager`, which routes repository requests through `RepoHub` and a `RepoRuntime`. A repository runtime coordinates its `IndexManager`, `ResourceManager`, search state, and lifecycle flags. This prevents a request for repository A from accidentally using a daemon state or store belonging to repository B.

`server.py` provides the HTTP serving layer. `daemon.py` provides process/control behavior. The CLI can run a foreground service with `scubiee serve`, while `scubiee engine` controls start, stop, status, ensure, run, watchdog, supervisor, and autostart operations.

### Standby and idle behavior

The runtime supports standby/idle/autostart transitions. Background sync and automatic indexing are policy-controlled rather than hard-coded into every client call. MCP/serve entry points establish safe defaults such as background sync enabled, automatic indexing enabled, full background rebuilds disabled by default, and an idle timeout.

### Watchdog

`watchdog.py` is a separate recovery/monitoring boundary. It can be disabled with `CTX_WATCHDOG=0`; its polling interval is controlled by `CTX_WATCHDOG_INTERVAL_S`. When enabled, it observes runtime state and can wake/reconcile or restart the daemon according to the stored engine metadata and lifecycle policy.

## MCP surfaces and managed gating

### Surface selection

`mcp_locate.py` selects the active surface from `CTX_MCP_SURFACE`. The product default is `phase`:

| Surface | Tools |
| --- | --- |
| `phase` | `map`, `focus`, `grep`, `glob`, `workspace`, `status` |
| `read` | `search`, `read`, `status` |
| `nav` | `search`, `files`, `read`, `recall`, `expand`, `status` |
| `graph` | `search`, `neighbors`, `graph`, `status` |
| `rich` | `search`, `read`, `outline`, `status` |
| `search` | `search`, `status` |
| `grep` | `grep`, `status` |

The phase surface is optimized for a staged discovery workflow: map the area, focus on a relevant span, inspect exact text or file paths, and maintain workspace context.

### The global rule contract

`scubiee connect` installs both a client-specific MCP configuration and a global instruction where the client supports one. The instruction is deliberately conditional because global rules are loaded before the repository's Scubiee state is known:

```text
call status() once
if managed == true and ok == true:
    use Scubiee discovery tools
else:
    explicitly ignore this Scubiee rule for the rest of the session
    use native search/read tools
```

The rule does not authorize indexing, registration, or writes. It is a discovery-routing instruction. MCP tools are annotated as read-only/idempotent where applicable, while repository enrollment and destructive lifecycle actions remain explicit CLI operations.

### Managed-state check

`_is_repo_managed` requires a usable repository context and managed project evidence. `_server_instructions` provides the client-facing routing guidance. If `CTX_REPO` is absent, the workspace path is not managed, or the daemon/MCP health check fails, CE should not be forced into the session.

This behavior is important for two reasons:

- a global rule can be installed once without contaminating unrelated folders; and
- an assistant can continue working with native tools when Scubiee is unavailable rather than retrying a denied or impossible Scubiee request.

## Identity and Git worktree reconciliation

Project identity is a safety boundary, not merely a cache key. The resolution sequence considers:

1. a valid in-repository ID file;
2. trusted registry path evidence;
3. store evidence for a known project;
4. Git common-directory/worktree-family relationships; and
5. a newly minted `ce_...` project ID when no existing identity is trustworthy.

A Git worktree may have a `.git` pointer file rather than a `.git` directory. The resolver must therefore use Git common-directory evidence without incorrectly rejecting worktrees as outside the repository root. Reconciliation can select a canonical existing identity and supersede duplicate records rather than creating independent indexes for every linked path.

When a repository moves, is re-opened through a worktree, or has duplicate ID evidence, `scubiee init`/`scubiee initialize` should be preferred over manually editing IDs. The lifecycle path reconciles identity and then performs the appropriate incremental or full freshness operation.

## Provider selection and fallback

The provider path is explicit and capability-aware:

| Profile | Runtime intent |
| --- | --- |
| `cuda` | Linux NVIDIA GPU / `onnxruntime-gpu` / FP16 model |
| `dml` | Windows DirectML / `onnxruntime-directml` / FP16 model |
| `mlx` | Apple Silicon MLX when available / FP16 model |
| `coreml` | Explicit CoreML path / FP16 model |
| `cpu` | CPU with INT8 quantized model (auto-created during setup) |

`accel.py` and `runtime_profile.py` determine what can actually run; `embedder.py` prepares CodeRankEmbed; `preflight.py` validates the prerequisites. A provider/capability failure fails closed at the relevant boundary. The system should not publish a semantically incomplete index while reporting the provider as healthy.

### Model precision by profile

| Profile | Model file | Size | Why |
| --- | --- | --- | --- |
| `dml` / `cuda` / `mlx` / `coreml` | `model_fp16.onnx` | ~260 MB | GPUs have native FP16 support, full precision |
| `cpu` | `model_int8.onnx` | ~132 MB | INT8 uses CPU VNNI/AMX instructions, 1.5x faster than FP16 on CPU |

FP32 (`model.onnx`, 522 MB) is **never used for inference**. It exists only as the download source from HuggingFace, converted to FP16 during setup. The INT8 model is dynamically quantized from FP16 during setup when a CPU profile is selected.

### CPU thread budget

CPU-only profiles use a dual-budget strategy controlled by `IndexMemoryBudget.cpu_thread_pct`:

| Operation | CPU budget | Rationale |
| --- | --- | --- |
| Bootstrap / full reindex | 35% of cores (min 2) | One-time cost, users expect to wait |
| Background incremental sync | 15% of cores (min 1) | Must be invisible during active coding |

The budget is applied via `CTX_CPU_EMBED_THREADS` env var, consumed by `embedder.py` when initializing FastEmbed with `threads=N`. GPU profiles ignore this entirely ? they set `threads=1` and offload compute to the GPU.

### GPU auto-repair

`validate_dml_provider()` runs at engine startup. If the expected GPU execution provider is missing (e.g., a package upgrade pulled a newer `onnxruntime` that shadowed the DML wheel), it automatically reinstalls the correct ORT wheel and re-validates. Only reports failure after repair fails. Never silently falls back to CPU ? users paid for GPU hardware.

## Storage and publication invariants

### Local storage

| Path | Ownership |
| --- | --- |
| `<repo>/.scubiee/id.json` | Repository-local identity evidence |
| `~/.scubiee/prefs.json` | User preferences |
| `~/.scubiee/registry.json` | Trusted managed-project registry |
| `~/.scubiee/projects/<project_id>/` | Per-project index/runtime store |
| `~/.scubiee/vectordb/` | FAISS/TurboQuant vector root and catalog |

`CTX_VECTORDB_ROOT` can override the default vector root. MCP/daemon entries also carry runtime environment such as `CTX_ENGINE_URL`, `CTX_REPO`, `CTX_MCP_SURFACE`, and background-sync defaults.

### Invariants operators should preserve

- Repository identity and registry state must agree well enough for the daemon to route requests to the intended project.
- A denied or never-indexed repository must not receive an automatic index.
- Provider and capability checks must pass before embedding/publishing work.
- Retrieval must use a consistent published generation, not a partially written artifact set.
- Incremental changes must update Merkle, chunk, metadata, graph, and vector state together or escalate to a full rebuild.
- A daemon bound to one repository must not silently answer a request for another repository.
- Removing a repository store and wiping all machine data are explicit operations, not side effects of a normal search or status call.

## Operational runbook

### First installation

```bash
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee preflight
scubiee connect --all --dry-run
scubiee init C:\src\repository
scubiee connect --cursor
scubiee status C:\src\repository
```

### Health check before a release

```bash
scubiee preflight C:\src\repository
scubiee doctor C:\src\repository --all
scubiee resources --refresh
scubiee certify C:\src\repository --canary
scubiee test quick
scubiee test core
```

### Diagnose a client that cannot retrieve context

```bash
scubiee status C:\src\repository
scubiee engine status C:\src\repository
scubiee connect --cursor --dry-run
scubiee mcp C:\src\repository
```

Check the following in order:

1. the client has a `scubiee` MCP entry;
2. the entry uses the intended Python interpreter and `CTX_ENGINE_URL`;
3. `CTX_REPO` is absent only when the client can provide the workspace path;
4. `scubiee status` reports the repository as managed and healthy; and
5. the selected MCP surface exposes the expected tool names.

### Refresh a stale index

```bash
scubiee status C:\src\repository
scubiee sync C:\src\repository
# Immediate lifecycle reconciliation:
scubiee sync-now C:\src\repository
# Full rebuild when status or change size requires it:
scubiee rebuild C:\src\repository
```

### Repair or migrate

```bash
scubiee setup --repair
scubiee doctor --all --fix
scubiee migrate C:\src\repository --check-all
scubiee migrate C:\src\repository --apply
```

### Complete cleanup

```bash
# Nuclear: remove everything Scubiee created (+ package)
scubiee wipe --all --confirm --package

# If the CLI is already gone / locked on Windows:
#   scubiee unlock-tool
#   then re-run wipe, or use scripts/uninstall-uv-scubiee.ps1
```

## Failure modes and safety boundaries

| Condition | Expected behavior | Operator response |
| --- | --- | --- |
| Repository is not managed | MCP status reports unmanaged/not healthy for CE use; the global rule tells the AI to use native tools | Run `scubiee init PATH` if Scubiee is intended for the repository |
| MCP has no repository context | The adapter cannot safely infer the target project | Supply the workspace path or configure `CTX_REPO` in the client entry |
| Daemon is down or bound to another repository | Search/status fails or reports unhealthy rather than crossing repository boundaries | Run `scubiee engine status`, then `scubiee engine ensure`/`start` for the intended repository |
| Provider/model capability is missing | Preflight/setup/indexing fails closed | Repair the profile or explicitly choose `cpu` |
| Large change set | Live sync escalates to a guarded full-index path | Allow the rebuild or run `scubiee rebuild` deliberately |
| Duplicate/moved/worktree identity | Resolver and Git-family reconciliation choose or mint identity based on evidence | Use `scubiee init`/`scubiee initialize`; do not hand-edit IDs first |
| Repository is intentionally excluded | `never-index` persists a denial | Use `scubiee never-index PATH --reason ...` only when exclusion is intended |
| Destructive cleanup requested | Removal/wipe requires explicit command and, for wipe, confirmation | Review `--dry-run` output before `--confirm` |

## Extension and documentation guidance

When adding a new coding-tool integration, update the tool registry, MCP writer/template behavior, global-rule semantics, installer tests, and the public integration table together. A client entry is not enough: the tool must also receive an instruction compatible with its rule model, or be documented as MCP-only when it has no standalone global rule file.

When changing indexing or retrieval, update both the public product explanation and this internal pipeline description. In particular, preserve the distinction between:

- machine setup versus repository enrollment;
- full indexing versus incremental/live sync;
- lexical, dense, and graph retrieval signals;
- managed-state gating versus tool configuration; and
- repository removal versus machine-wide wipe.

The current source files are the authority for implementation details: `packages/pipeline/__main__.py`, `indexer.py`, `incremental.py`, `ce_service.py`, `server.py`, `daemon.py`, `lifecycle_runtime.py`, `watchdog.py`, `project_id.py`, `git_family.py`, `repo_lifecycle.py`, `mcp_locate.py`, `mcp_install.py`, `tool_registry.py`, and `rules_installer.py`.
