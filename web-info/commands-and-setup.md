# Scubiee: Commands, Setup, and Product Guide

> **Documentation baseline:** Scubiee `0.2.29`
> **Audience:** product pages, documentation websites, and developers using Scubiee from a terminal or an AI coding tool.

Scubiee is a local-first code context product. Its Context Engine builds a searchable representation of a repository, keeps that representation fresh as files change, and exposes the result through a CLI, a local daemon, and MCP integrations for AI coding tools.

This guide is the user-facing source for what Scubiee does, when to use each command, and how to install and operate it. The implementation and operational model are documented separately in [`context-engine-internals.md`](./context-engine-internals.md).

## What Scubiee is

Most coding assistants can read files, but a large repository makes ad-hoc file search noisy, slow, and easy to misdirect. Scubiee adds a repository-aware context layer that can:

- index source files into symbol- and file-oriented chunks;
- combine lexical, dense-vector, and graph-aware retrieval;
- preserve repository identity across normal Git repositories, linked worktrees, and moves;
- incrementally re-index changed files instead of rebuilding everything for every edit;
- serve context locally through a managed daemon and MCP;
- install the MCP configuration and a global, self-gating AI rule for supported coding tools; and
- run diagnostics, certification checks, lifecycle controls, and repair operations from one CLI.

Scubiee is not a replacement for the coding assistant. It is the local context and repository-lifecycle layer that the assistant can call when the current repository is enrolled and healthy.

### Product value in one sentence

**Scubiee turns a repository into continuously maintained, tool-agnostic context without forcing an AI assistant to guess which files matter.**

## Who should use it

- **Individual developers:** make a repository searchable by meaning and structure without uploading the code to a context service.
- **Teams building AI coding workflows:** give Cursor, Claude Code, Codex, Kiro, and other clients a common local MCP backend.
- **Large or active repositories:** keep context current through incremental and live re-indexing.
- **Operators and release engineers:** inspect readiness, provider capabilities, daemon state, repository identity, and data health from the CLI.
- **Documentation and platform teams:** use the command and integration tables below as the basis for a product or docs website.

## Quick start

### 1. Install the package

```powershell
python -m pip install -U scubiee
```

For a reproducible version of this documentation baseline:

```powershell
python -m pip install scubiee==0.2.28
```

The `ctx` executable is the normal user-facing entry point. `python -m pipeline` is useful in a source checkout or when diagnosing the Python installation.

### 2. Set up the machine once

```powershell
ctx setup
```

`ctx setup` is machine setup, not repository enrollment. It detects or installs a suitable runtime/provider, prepares the CodeRankEmbed embedding model, calibrates the local configuration, installs runtime support, and configures the local MCP/daemon integration.

Choose a provider explicitly when required:

```powershell
ctx setup --profile dml       # Windows DirectML
ctx setup --profile cuda      # Linux NVIDIA CUDA
ctx setup --profile mlx       # Apple Silicon MLX
ctx setup --profile coreml    # explicit CoreML path
ctx setup --profile cpu       # CPU fallback
```

### 3. Enroll and index a repository

```powershell
ctx init "C:\src\my-repository"
```

This registers the repository with Context Engine, creates or reconciles its project identity, indexes it by default, and ensures that the local daemon can serve it.

Useful variants:

```powershell
# Enroll now, but defer indexing.
ctx init "C:\src\my-repository" --no-index

# Use the fast configuration and selected roots.
ctx init "C:\src\my-repository" --fast --roots src,packages
```

### 4. Verify readiness

```powershell
ctx status "C:\src\my-repository"
ctx preflight "C:\src\my-repository"
```

Use `status` for the operational state of a specific repository. Use `preflight` for local dependency and capability checks before indexing or certification.

## Machine setup versus repository enrollment

These are intentionally separate operations:

| Operation | What it changes | When to use it |
| --- | --- | --- |
| `ctx setup` | Machine-level providers, runtime, model preparation, calibration, supervisor, and MCP defaults | Once per machine, after installation, or with `--repair` when setup is damaged |
| `ctx init PATH` | Repository enrollment, project identity, initial index, and daemon readiness | For every repository that should receive Context Engine context |
| `ctx register PATH` | Explicit registration with optional indexing and registration-policy controls | When a script or operator wants registration separate from the friendly `init` flow |
| `ctx initialize PATH` | Initialize or reconcile a managed repository lifecycle | When integrating with lifecycle code or repairing an existing managed repository |
| `ctx index PATH` | Build or rebuild the repository search artifacts | When a first index is needed, or when a full rebuild is intentional |

Historical examples that pass `--profile` or `--status` to `ctx init` are stale. Provider selection and machine status belong to `ctx setup`; repository status belongs to `ctx status`.

When an existing index has more than 200 changed or removed files, `ctx init` pauses for safety instead of processing the entire drift automatically. Review the repository and explicitly continue with `ctx init --confirm` (or `ctx init <PATH> --confirm` for another path).

## Providers and installation profiles

The production embedding model is **`nomic-ai/CodeRankEmbed`**. The selected runtime depends on the profile and the hardware available on the machine.

| Profile | Intended environment | Runtime/provider guidance |
| --- | --- | --- |
| `cuda` | Linux with an NVIDIA GPU | CUDA acceleration through the GPU ONNX Runtime package |
| `dml` | Windows with a supported GPU | DirectML through `onnxruntime-directml` |
| `mlx` | Apple Silicon | MLX when available |
| `coreml` | Explicit Apple/CoreML route, including supported Mac configurations | CoreML provider path |
| `cpu` | Any machine without a usable accelerator, or a deliberate fallback | CPU execution |

With no explicit profile, setup chooses an appropriate configuration when it can. An explicit profile is useful for CI, troubleshooting, or a machine where automatic detection is not the desired policy.

### Windows DirectML notes

On Windows, `dml` is the GPU-oriented profile. A successful setup still depends on a usable graphics driver and the local DirectML/ONNX Runtime dependencies. If GPU setup is unavailable, use `ctx setup --profile cpu` rather than assuming that a failed provider install is an indexing success.

Recommended checks:

```powershell
ctx setup --profile dml
ctx preflight
ctx resources --refresh
ctx doctor --all
```

## CLI reference

Run `ctx --help` or `ctx <command> --help` for the complete parser help. The following tables describe the current command surface and the practical reason to use each command.

### Indexing and repository lifecycle

| Command | When and why | Example |
| --- | --- | --- |
| `ctx index [PATH]` | Build the repository index. Use `--force` for a deliberate full rebuild, `--bits N` to select compression precision, `--model MODEL` to choose an embedding model, `--fast` for the fast scope, or `--roots CSV` to restrict roots. | `ctx index C:\src\app --force` |
| `ctx init [PATH]` | Enroll a repository, reconcile its identity, index it by default, and ensure the daemon. Use `--no-index`, `--allow-once`, `--fast`, `--roots CSV`, or `--confirm` when controlling the initial flow. | `ctx init C:\src\app --fast --roots src,lib` |
| `ctx register [PATH]` | Perform explicit project registration. Use `--always-allow` for the registration policy, `--no-index` to defer indexing, `--fast`, or `--force` when the operation must be repeated. | `ctx register C:\src\app --no-index` |
| `ctx initialize [PATH]` | Initialize a managed repository and reconcile an existing index. Use `--no-index` or `--allow-once` to control initial indexing/consent behavior. | `ctx initialize C:\src\app` |
| `ctx activate [PATH]` | Activate a previously managed repository when work resumes. | `ctx activate C:\src\app` |
| `ctx pause [PATH]` | Pause repository background work without removing its management state. Use `--reason` to record why. | `ctx pause C:\src\app --reason "large refactor"` |
| `ctx resume [PATH]` | Resume background work for a paused repository. | `ctx resume C:\src\app` |
| `ctx sync-now [PATH]` | Ask the runtime to reconcile repository freshness immediately. | `ctx sync-now C:\src\app` |
| `ctx rebuild [PATH]` | Force a full repository rebuild through the lifecycle/runtime path. | `ctx rebuild C:\src\app` |
| `ctx remove [PATH]` | Remove repository lifecycle management. Add `--delete-store` only when the repository's local Context Engine store should also be deleted. | `ctx remove C:\src\app` |
| `ctx never-index [PATH]` | Persistently deny indexing for a repository. Use `--reason` to make the policy understandable to operators. | `ctx never-index C:\src\vendor --reason "third-party source"` |
| `ctx list` | List repositories known to the local registry as JSON. | `ctx list` |

### Search, daemon, and MCP operations

| Command | When and why | Example |
| --- | --- | --- |
| `ctx search QUERY [PATH]` | Search a repository from the CLI. Use `--top-k N` to control result count, `--local` to avoid the warm server path, or `--url URL` to target a daemon explicitly. | `ctx search "authentication middleware" C:\src\app --top-k 8` |
| `ctx status [PATH]` | Inspect index freshness, repository management, and daemon-facing status. Use `--url URL` to query a specific daemon. | `ctx status C:\src\app` |
| `ctx sync [PATH]` | Run incremental re-embedding for files changed since the last index. | `ctx sync C:\src\app` |
| `ctx serve [PATH]` | Run the Context Engine HTTP daemon in the foreground. Use `--host HOST` and `--port PORT` to bind it explicitly. | `ctx serve C:\src\app --host 127.0.0.1 --port 8765` |
| `ctx mcp [PATH]` | Start the thin MCP adapter that forwards tool requests to the Context Engine daemon. | `ctx mcp C:\src\app` |
| `ctx dashboard [stop]` | Start or control the dedicated localhost operator dashboard. Use `--no-open` to avoid opening a browser or `--status` to inspect it. | `ctx dashboard --no-open` |
| `ctx engine ACTION [PATH]` | Control the daemon and supervisor: `start`, `stop`, `status`, `run`, `ensure`, `watchdog`, `supervisor`, or `autostart`. Relevant controls include `--host`, `--port`, `--wait`, `--no-open`, `--logon`, and `--off`. | `ctx engine status C:\src\app` |

The normal end-user path is `ctx init` followed by a coding-tool MCP call. Use `serve` and `engine` directly when operating the daemon, debugging a client, or running a foreground process.

### Setup, diagnostics, and verification

| Command | When and why | Example |
| --- | --- | --- |
| `ctx setup` | Prepare or repair the machine runtime and provider. Profiles are `cuda`, `dml`, `mlx`, `coreml`, and `cpu`. Setup also accepts `--skip-install`, `--skip-model`, `--skip-bench`, `--skip-accel`, `--repair`, `--index PATH`, `--repo PATH`, `--register`, `--host`, `--port`, `--wait`, and `--status`. | `ctx setup --repair --status` |
| `ctx resources` | Inspect hardware and adaptive resource pressure. Use `--refresh`, `--save`, or `--reset-rm` when collecting or resetting the resource snapshot. | `ctx resources --refresh` |
| `ctx preflight [PATH]` | Check required local dependencies and capabilities before an operation. Use `--lexical-only` when validating without embedding requirements. | `ctx preflight C:\src\app --lexical-only` |
| `ctx doctor [PATH]` | Read readiness and repair diagnostics. Use `--all` for the broad report and `--fix` when applying supported repairs. | `ctx doctor C:\src\app --all --fix` |
| `ctx certify [PATH]` | Run the release/certification gate. Use `--skip-daemon` to omit daemon checks or `--canary` to include the canary path. | `ctx certify C:\src\app --canary` |
| `ctx test TIER [PATH]` | Run verification tiers: `quick`, `core`, `fault`, `install`, `clients`, or `all`. The client-focused path also accepts `--clients`. | `ctx test core` |
| `ctx diagnose` | Produce a diagnostic report. Use `--no-tests` to avoid test execution or `--output PATH` to choose the log/report location. | `ctx diagnose --no-tests --output C:\temp\scubiee-diagnose.json` |
| `ctx migrate [PATH]` | Inspect or apply data migrations after an upgrade. Use `--apply`, `--apply-all`, `--check-all`, and `--force` according to the migration operation. | `ctx migrate C:\src\app --check-all` |
| `ctx settings` | Show or change registration and background-indexing preferences. Use `--show`, `--mode automatic|mcp_cli`, `--incremental BOOL`, and `--watching BOOL`. | `ctx settings --show` |
| `ctx wipe` | Remove Context Engine data from the machine. This is destructive: use `--dry-run` to inspect the plan and require `--confirm` for an actual wipe. `--include-repos` and `--include-mcp` broaden what is removed. | `ctx wipe --dry-run` |

### Integration installation

| Command | When and why | Example |
| --- | --- | --- |
| `ctx install rules` | Install or refresh the global Context Engine MCP entry and the tool-specific global rule/instruction where that tool supports a file-based rule. | `ctx install rules --cursor --claude-code --kiro` |

Supported selection flags are `--cursor`, `--claude-code`, `--codex`, `--kiro`, `--windsurf`, `--copilot`, `--cline`, `--roo-code`, `--continue`, `--zed`, and `--opencode`. Use multiple flags in one invocation, `--all` for every implemented target, and `--dry-run` to see the paths without writing them.

```powershell
# Preview all supported writes.
ctx install rules --all --dry-run

# Install only the tools currently used on a workstation.
ctx install rules --cursor --claude-code --opencode
```

The installer merges/replaces only the `context-engine` MCP entry in JSON-style configs. Append-style instruction files use an idempotent marked section. Standalone generated rule files are written by the installer, so review an existing file before replacing it. `--dry-run` is the safe way to inspect the target paths first.

## MCP and global-rule integrations

After `ctx setup` or `ctx install rules`, a supported coding tool can launch the local Context Engine MCP adapter. The current default is:

```text
CTX_MCP_SURFACE=phase
```

The phase surface exposes:

- `map` — locate the most relevant repository areas;
- `focus` — deepen a selected file/span and inspect related context;
- `grep` — perform exact text/regex discovery;
- `glob` — locate files by path pattern;
- `workspace` — inspect or pin session context; and
- `status` — check management and health.

Legacy or specialized surfaces remain selectable through `CTX_MCP_SURFACE`: `read`, `nav`, `graph`, `rich`, `search`, and `grep`. Their available tools are summarized in the internal guide.

### Managed versus unmanaged repositories

The installed global rule is deliberately self-gating:

1. The AI tool calls `status()` once.
2. If `status.managed` and `status.ok` are both true, it uses Context Engine discovery tools.
3. If the repository is unmanaged, or the MCP is unavailable/unhealthy, it explicitly ignores the Context Engine rule for the rest of the session and uses its native search/read tools.

Installing a global rule therefore does not force Context Engine onto every folder. A repository must be enrolled with `ctx init`/`ctx register`, and the MCP must be healthy, before the rule recommends CE discovery.

### Implemented targets and their user-level paths

The installer uses these paths relative to the current user's home directory (`~`; on Windows this is normally `%USERPROFILE%`).

| Tool | MCP config | File-based global rule/instruction | Important limitation |
| --- | --- | --- | --- |
| Cursor | `~/.cursor/mcp.json` | `~/.cursor/rules/context-engine.mdc` | Cursor uses MDC rule format. |
| Claude Code | `~/.claude.json` | `~/.claude/CLAUDE.md` | The rule is appended as an idempotent section. |
| Codex (OpenAI) | `~/.codex/config.toml` | `~/.codex/instructions.md` | TOML MCP configuration; instruction file is appended. |
| Kiro | `~/.kiro/settings/mcp.json` | `~/.kiro/steering/context-engine.md` | Uses Kiro steering markdown. |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | No standalone file-based global rule | The MCP entry carries the integration instruction. |
| VS Code / Copilot | `~/.vscode/mcp.json` | `~/.github/copilot-instructions.md` | Uses the VS Code/Copilot `servers` key, not `mcpServers`. |
| Cline | `~/.cline/mcp.json` | `~/.cline/rules/context-engine.md` | Uses the Cline rules location. |
| Roo Code | `~/.cline/mcp.json` | `~/.cline/rules/context-engine.md` | Roo Code currently shares the Cline paths. |
| Continue | `~/.continue/config.yaml` | `~/.continue/rules/context-engine.md` | MCP entry is written in YAML. |
| Zed | `~/.config/zed/settings.json` | No standalone file-based global rule | Instruction is carried in the MCP/server description. |
| OpenCode | `~/.config/opencode/config.json` | `~/.config/opencode/instructions.md` | Instruction file is appended. |

Aider is not listed as an implemented target because it does not provide a native MCP client integration in the current product. Do not describe `ctx install rules --aider` as supported.

## Data locations

Scubiee keeps repository identity, preferences, registry state, and vector data in local Context Engine locations:

| Location | Purpose |
| --- | --- |
| `<repo>/.context-engine/id.json` | Repository-local project identity evidence. |
| `~/.context-engine/prefs.json` | User-level registration and indexing preferences. |
| `~/.context-engine/registry.json` | Trusted registry of managed projects. |
| `~/.context-engine/projects/<project_id>/` | Per-project index/runtime artifacts. |
| `~/.context-engine/vectordb/` | Local vector database and catalog; override the root with `CTX_VECTORDB_ROOT`. |

Do not edit generated index artifacts while the daemon is active. Use lifecycle commands such as `ctx rebuild`, `ctx remove`, `ctx migrate`, or `ctx wipe` so identity and registry state remain consistent.

## Environment variables

Most users should use CLI flags. These variables are useful for MCP, automation, or advanced operations:

| Variable | Meaning |
| --- | --- |
| `CTX_REPO` | Repository root used by an MCP/daemon process when no path is passed explicitly. |
| `CTX_ENGINE_URL` | Explicit daemon URL, for example `http://127.0.0.1:8765`. |
| `CTX_SEARCH_URL` | Explicit search service URL for CLI/search integrations. |
| `CTX_MCP_SURFACE` | MCP tool surface; the product default is `phase`. |
| `CTX_VECTORDB_ROOT` | Override `~/.context-engine/vectordb/`. |
| `CTX_REGISTRATION_MODE` | Registration policy, normally `automatic` or `mcp_cli`. |
| `CTX_FAST_ROOTS` | Comma-separated roots used by fast indexing when `--roots` is not supplied. |
| `CTX_INCREMENTAL_MAX_TOUCH` | Advanced override for the changed/removed-file safety cap; the default is 200, and `ctx init --confirm` is preferred for an intentional one-off override. |
| `CTX_BACKGROUND_SYNC` | Enable or disable background synchronization. |
| `CTX_AUTO_INDEX` | Enable or disable automatic indexing behavior. |
| `CTX_WATCHDOG` | Enable or disable the watchdog process. |
| `CTX_TOKEN_MODE` | Token-budget mode used by context/session tooling; the installed integration defaults to `savings`. |

The installer also supplies runtime defaults such as `CTX_ALLOW_BG_FULL=0`, `CTX_SYNC_INTERVAL_MS=300000`, and `CTX_ENGINE_IDLE_S=60` to the generated MCP entry. Change these only when operating the runtime deliberately.

## Common workflows

### New workstation and first repository

```powershell
python -m pip install -U scubiee
ctx setup
ctx install rules --cursor --claude-code --kiro --opencode
ctx init "C:\src\my-repository"
ctx status "C:\src\my-repository"
```

### Add a second repository without repeating machine setup

```powershell
ctx init "C:\src\another-repository"
ctx status "C:\src\another-repository"
```

### Repair a machine or provider installation

```powershell
ctx setup --repair
ctx preflight
ctx doctor --all --fix
ctx resources --refresh
```

### Refresh a repository after a large change

```powershell
ctx status "C:\src\my-repository"
ctx sync-now "C:\src\my-repository"
# Use only when a complete rebuild is justified:
ctx rebuild "C:\src\my-repository"
```

### Install integrations safely

```powershell
ctx install rules --all --dry-run
ctx install rules --cursor --claude-code --codex --kiro --opencode
```

### Release or environment certification

```powershell
ctx preflight "C:\src\my-repository"
ctx doctor "C:\src\my-repository" --all
ctx certify "C:\src\my-repository" --canary
ctx test core
```

## Troubleshooting guide

### The AI tool is not using Context Engine

1. Run `ctx status <repo>` and confirm the repository is managed and the daemon is reachable.
2. Run `ctx install rules <tool flag> --dry-run` to confirm the global paths.
3. Check that the tool's MCP configuration contains a `context-engine` entry.
4. Check `CTX_REPO` or the workspace path if the adapter cannot identify the repository.
5. Run `ctx mcp <repo>` or `ctx engine status <repo>` when testing the adapter/daemon directly.

If the repository is unmanaged, this is expected behavior: the global rule tells the AI to skip CE tools and use native discovery rather than returning a misleading CE error.

### Setup cannot use the GPU

Run `ctx preflight` and `ctx resources --refresh`, then choose an explicit supported profile. On Windows, try `ctx setup --profile dml`; if the local driver/runtime is not usable, choose `ctx setup --profile cpu`.

### The index is stale

Use `ctx status`, then `ctx sync` or `ctx sync-now`. If the changed set is too large for safe incremental processing, the runtime's full-index guard will require or select a rebuild; use `ctx rebuild` when the status indicates that a full rebuild is needed.

### A repository was moved or is a Git worktree

Run `ctx init <new-path>` or `ctx initialize <new-path>`. Context Engine reconciles local IDs, trusted registry evidence, store evidence, and the Git common directory/worktree family rather than blindly minting a second project.

### A tool already has configuration

Use `ctx install rules --<tool> --dry-run` first. The installer preserves unrelated JSON/TOML/YAML configuration where its format writer supports merging, replaces only the Context Engine MCP entry, and uses marked replacement for append-style rule sections. Review standalone generated rule files before allowing them to replace an existing file.

## Source-of-truth note

This guide intentionally describes the current `0.2.28` command and integration surface rather than copying older README or setup examples. When command behavior changes, update this guide together with `packages/pipeline/__main__.py`, `packages/pipeline/tool_registry.py`, and `packages/pipeline/rules_installer.py`.
