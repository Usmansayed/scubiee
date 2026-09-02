# Scubiee complete CLI reference

> **Version:** 0.3.14  
> **Source of truth:** `packages/pipeline/__main__.py`  
> **Concepts:** [How everything works](./how-everything-works.md) · **Paths:** [Data & files reference](./data-and-files-reference.md)  
> **Quick tables:** [docs/web-info/commands-reference.md](../docs/web-info/commands-reference.md)

This is the **exhaustive CLI guide** — not just flags, but **why each command exists**, what it changes on disk, how it interacts with the daemon and MCP, common mistakes, and how to recover when something goes wrong.

Run `scubiee <subcommand> --help` on your installed version to confirm flags match your build.

---

## Table of contents

### Foundations
1. [Mental model — three programs, four layers](#mental-model--three-programs-four-layers)
2. [Recommended workflows](#recommended-workflows)
3. [Invocation, output & guards](#invocation-output--guards)
4. [Exit codes & JSON](#exit-codes--json)
5. [Safety gates (`--confirm`)](#safety-gates-confirm)
6. [Environment variables the CLI sets or reads](#environment-variables-the-cli-sets-or-reads)

### Command reference (by category)
7. [Install & machine](#install--machine)
8. [Project lifecycle](#project-lifecycle)
9. [Index & search](#index--search)
10. [Diagnostics & certification](#diagnostics--certification)
11. [Engine, serve & dashboard](#engine-serve--dashboard)
12. [Global stop, halt & unlock](#global-stop-halt--unlock)
13. [Connect & disconnect](#connect--disconnect)
14. [Upgrade & migrate](#upgrade--migrate)
15. [Settings & wipe](#settings--wipe)
16. [MCP adapter (CLI)](#mcp-adapter-cli)

### Reference tables
17. [Command relationships (which to use when)](#command-relationships-which-to-use-when)
18. [Lifecycle decision matrix](#lifecycle-decision-matrix)
19. [Commands allowed when globally stopped](#commands-allowed-when-globally-stopped)
20. [Full command index](#full-command-index)

### Deep reference (new)
21. [JSON output glossaries](#json-output-glossaries)
22. [Symptom → command FAQ](#symptom--command-faq)
23. [Platform-specific behavior](#platform-specific-behavior)

---

## Mental model — three programs, four layers

Scubiee is **local software**, not a cloud API and not an IDE extension. Three processes share one Python package:

```text
┌─────────────┐     ┌─────────────┐     ┌─────────────────────┐
│ scubiee CLI │     │ scubiee mcp │     │ Scubiee engine      │
│ (you run)   │     │ (IDE runs)  │     │ (background daemon) │
└──────┬──────┘     └──────┬──────┘     └──────────┬──────────┘
       │                   │                        │
       └───────────────────┴────────────────────────┘
                           │
                    ~/.scubiee + <repo>/.scubiee
```

| Process | How it starts | Role |
|---------|---------------|------|
| **CLI** | You type `scubiee …` | Setup, init, connect, doctor, wipe, upgrade |
| **MCP adapter** | IDE spawns via MCP config | Forwards agent tool calls (`map`, `focus`, `grep`, …) to engine |
| **Engine** | `setup`, first MCP call, or `engine start` | HTTP on `127.0.0.1:8765`; owns indexes, embeds, search |

### The four layers (most problems = missing layer)

| Layer | Question | Key command | On-disk proof |
|-------|----------|-------------|---------------|
| **1. Install** | Is `scubiee` on PATH? | `uv tool install scubiee` | `scubiee --version` works |
| **2. Machine setup** | GPU/CPU + model ready? | `scubiee setup` | `~/.scubiee/accel.json` |
| **3. Repo enrollment** | Is *this folder* indexed? | `scubiee init .` | `<repo>/.scubiee/id.json` |
| **4. IDE wiring** | Does the agent call MCP? | `scubiee connect --cursor` | `~/.cursor/mcp.json` + rules |

**Critical:** `init` completes layer 3 only. Without `connect` (layer 4), agents show `managed: false` and fall back to native search — even if indexing succeeded.

**Critical:** `connect` completes layer 4 only. Without `setup` + `init`, MCP tools have nothing to search.

---

## Recommended workflows

### First-time install (new machine)

```bash
# 1. Install package (pick one method)
uv tool install scubiee --index-url https://pypi.org/simple

# 2. Machine setup — GPU detect, model download, calibration (~5–15 min first run)
scubiee setup

# 3. Enroll your project
cd /path/to/your/repo
scubiee init .

# 4. Wire your IDE (Cursor example)
scubiee connect --cursor

# 5. Reload MCP in Cursor (Settings → MCP → reload) or restart Cursor

# 6. Verify
scubiee doctor .
scubiee status .
```

**Why this order:** setup needs no repo; init needs accel profile; connect needs enrolled repos in registry to fan out project MCP pins.

### Daily development

You usually **do nothing** after setup — the daemon and background sync keep indexes fresh. When needed:

```bash
scubiee sync .              # After large git pull or branch switch
scubiee status .            # Check freshness / chunk counts
scubiee search "auth middleware" .   # Manual search from terminal
```

If the agent says code is missing from search → run `sync`, confirm file type is in index scope (fast mode = `.py` under roots only).

### After every upgrade

```bash
scubiee upgrade               # Or: uv tool install --force scubiee
scubiee setup --repair        # If doctor shows missing ORT/fastembed
scubiee connect --cursor      # Refresh MCP env + rules
# Reload MCP in IDE
scubiee doctor .
```

Upgrade changes Python code; MCP configs may still point at old env vars or rule text until `connect` rewrites them.

### Before uninstall or full wipe

```bash
scubiee halt                  # Stub MCP + kill processes (Cursor can stay open)
scubiee wipe --all --confirm  # Or single-repo: scubiee wipe . --confirm
```

On Windows, if upgrade/wipe fails with **Access denied**:

```bash
scubiee unlock-tool
uv tool install --force scubiee
scubiee setup --repair
scubiee connect --cursor
```

### CI / automation (non-interactive)

```bash
scubiee preflight . || exit 1
scubiee init /repo --confirm --fast --roots packages,src
scubiee certify /repo --skip-daemon
scubiee test quick /repo
```

Use `--confirm` whenever indexing might hit the safety gate (>25k indexable files or home/drive roots). Pipe stdout — commands emit JSON when not a TTY.

### Support bundle (attach to bug reports)

```bash
scubiee --version --verbose
scubiee setup --status
scubiee doctor .
scubiee list
scubiee diagnose --no-tests --desktop
```

Attach `Desktop/scubiee-diagnose.json` and tail of `~/.scubiee/engine.log`.

---

## Invocation, output & guards

### Basic form

```bash
scubiee <subcommand> [positional args...] [flags...]
```

- **Subcommand required** — bare `scubiee` prints help, exits non-zero.
- **Default path** — Most repo commands default `path` to `.` (cwd). Always `cd` to the repo or pass an absolute path when automating.
- **Help** — `scubiee <subcommand> --help` is always allowed, even when globally stopped.

### Version (no subcommand)

| Invocation | What you get |
|------------|--------------|
| `scubiee --version` / `-V` / `version` | One line: `scubiee X.Y.Z` |
| `scubiee --version --verbose` | Full **install identity**: which Python, uv tool path, duplicate installs on PATH |

When Scubiee is not “ready” (globally stopped, engine down, etc.), version commands print a **lifecycle hint** on stderr — e.g. `Globally stopped — run scubiee resume`.

**When to use verbose:** Any “wrong version” or “command not found but something runs” report. Doctor also surfaces install identity.

### Output modes

| Condition | CLI behavior |
|-----------|--------------|
| **Interactive terminal (TTY)** | Human summaries, progress bars, colors on stderr; minimal noise on stdout |
| **Piped / scripted (non-TTY)** | Structured **JSON on stdout** for most commands |
| **`scubiee status --json`** | Force JSON even on TTY |

**Tip for scripts:** Redirect stderr to a log file if you only want JSON: `scubiee status . 2>/dev/null`.

### Pre-command guards (run before your command)

Four guards can intercept a command before it executes:

#### 1. `CTX_HOME` guard

Ensures Scubiee’s data directory (`~/.scubiee` by default) is usable. Skipped for `--version`, `--help`, and `wipe` (wipe can clean a broken home).

Override home for testing: `CTX_HOME=/tmp/scubiee-test scubiee …` (advanced).

#### 2. Faiss guard

Most commands need the vector index library importable. If missing, Scubiee tries auto-repair once, then prints:

```text
[scubiee] … faiss …
[scubiee] Try: scubiee setup --repair
```

**Exempt commands** (work on broken installs): `setup`, `stop`, `halt`, `unlock-tool`, `wipe`, `doctor`, `preflight`, `test`, `connect`, `disconnect`, `migrate`, `diagnose`, `upgrade`, plus `engine stop|status|watchdog|supervisor|autostart`, `dashboard stop`.

#### 3. Global stop guard

After `scubiee stop`, most commands are **blocked** until `scubiee resume`. See [Commands allowed when globally stopped](#commands-allowed-when-globally-stopped).

#### 4. Auto-resume

These commands **automatically resume** if globally stopped (because you clearly intend to restore service):

- `scubiee connect …`
- `scubiee setup --repair`

If auto-resume fails, fix the reported error and run `scubiee resume` manually.

---

## Exit codes & JSON

| Code | Meaning | What to do |
|------|---------|------------|
| **0** | Success | — |
| **1** | Hard failure | Read JSON `error` / stderr; run `doctor` |
| **2** | **Confirm required** | Re-run with `--confirm` or answer TTY prompt |

Common JSON fields:

| Field | Meaning |
|-------|---------|
| `"ok": false` | Operation failed |
| `"error"` | Machine-readable reason |
| `"hint"` | Human fix suggestion |
| `"needs_confirm": true` | Safety gate — add `--confirm` |
| `"warning": "confirm_required"` | Same as confirm gate |
| `"deferred": true` | Index deferred due to resource pressure — retry later |

Full catalog: [Error codes reference](./error-codes-reference.md).

---

## Safety gates (`--confirm`)

Scubiee refuses to silently index enormous or dangerous paths. The gate counts **indexable files** (respecting skip rules — not raw `find | wc`).

### When `--confirm` is required

- Indexing **home directory**, **drive root** (`C:\`, `/`), or similar broad paths
- Trees with **>25,000 indexable files** (approximate; exact threshold in incremental preflight)
- Large **sync deltas** on the same paths

### Commands that accept `--confirm`

`init`, `index`, `register`, `initialize`, `sync`, `sync-now`

### Behavior

| Mode | Without `--confirm` on risky path |
|------|-----------------------------------|
| **TTY** | Interactive y/n prompt (init) or exit 2 with message |
| **Non-TTY** | Exit **2**, JSON with `needs_confirm` |

### Fast mode to avoid the gate

For monorepos, index code roots only:

```bash
scubiee init . --fast --roots packages,src,lib
```

---

## Environment variables the CLI sets or reads

| Variable | Set by | Purpose |
|----------|--------|---------|
| `CTX_HOME` | You (optional) | Override `~/.scubiee` data directory |
| `CTX_REPO` | `mcp`, `setup`, connect MCP entry | Default repo for engine/MCP |
| `CTX_ENGINE_URL` | `setup`, MCP config | Daemon URL (default `http://127.0.0.1:8765`) |
| `CTX_TOKEN_MODE` | MCP config | Token budget mode (`savings`) |
| `CTX_BACKGROUND_SYNC` | MCP config | Enable background sync from MCP |
| `CTX_REGISTRATION_MODE` | MCP config / settings | `automatic` or `mcp_cli` |
| `CTX_MCP_SURFACE` | MCP config | Tool surface (`phase`) |
| `CTX_FAST_ROOTS` | You (optional) | Default fast-index roots |
| `CTX_WATCHDOG` | You | `0` disables watchdog restarts |
| `CTX_RM_DISABLE` | You | `1` disables RAM-pressure throttling |
| `CTX_ALLOW_TEST_HOME` | Tests | Allow test CTX_HOME |
| `GRAPHIFY_QUIET` / `CTX_QUIET` | init (internal) | Suppress parse logs during progress bar |

Connect writes most MCP env vars into IDE config — you rarely set them manually.

---

## Install & machine

These commands configure **layer 2** (machine). They do not index your code.

---

### `scubiee setup`

**Purpose:** One-time (or repair) machine configuration — hardware detection, ONNX Runtime / FastEmbed install, CodeRank model download, batch calibration, session supervisor registration.

**When to run:**

| Situation | Command |
|-----------|---------|
| First install | `scubiee setup` |
| After upgrade, missing libs | `scubiee setup --repair` |
| Wrong GPU profile | `scubiee setup --repair --profile dml` |
| Check saved profile only | `scubiee setup --status` |

**What it does NOT do:** Index repos, write MCP (use `connect`), or enroll projects (use `init`).

#### Parameters (complete)

| Flag | Default | Description |
|------|---------|-------------|
| `--profile` | auto | Force `cuda`, `dml`, `mlx`, `coreml`, or `cpu` |
| `--skip-install` | false | Skip pip package install inside configure |
| `--skip-model` | false | Skip CodeRank model download |
| `--skip-bench` | false | Skip batch-size calibration |
| `--skip-accel` | false | Hardware snapshot only — no ORT/accel pip |
| `--repair` | false | Force full reconfigure; **auto-resumes** if globally stopped |
| `--index` | — | After setup, run `initialize_repo` on this path |
| `--repo` | `.` | Default repo for `CTX_REPO` / engine env |
| `--register` | false | Register `--repo` after supervisor install |
| `--host` | `127.0.0.1` | Engine bind host |
| `--port` | `8765` | Engine port |
| `--wait` | `120.0` | Health wait when starting engine |
| `--status` | false | Print `accel.json` JSON and exit (no install) |

#### Step-by-step (normal run)

1. Verify graphify engine modules import.
2. Ensure faiss importable (repair if needed).
3. Detect hardware → choose profile (CUDA / DML / MLX / CPU).
4. Pip-install profile-specific wheels into uv tool env (unless skipped).
5. Download CodeRank FP16 model to HuggingFace/FastEmbed cache.
6. Benchmark embed throughput → write batch size to `~/.scubiee/accel.json`.
7. Register **logon supervisor** (`install_session_runtime`) for auto engine lifecycle.

#### On disk after success

| Created/updated | Path |
|-----------------|------|
| Accel profile | `~/.scubiee/accel.json` |
| Hardware snapshot | `~/.scubiee/hardware.json` (may update) |
| Model cache | HF cache / fastembed paths (outside `.scubiee`) |
| Supervisor registration | OS-specific task/service |

#### Profile selection (typical)

| Machine | Profile | Why |
|---------|---------|-----|
| Windows + discrete GPU | `dml` | DirectML FP16 |
| Windows Intel iGPU only | `cpu` | DML on iGPU often hangs |
| Apple Silicon | `mlx` | Metal path |
| Linux + NVIDIA | `cuda` | CUDA ORT |
| Unknown / safe | `cpu` | Always works, slower |

#### Common mistakes

- Running `init` before `setup` → `machine_not_setup` error.
- Expecting MCP after setup → run `connect` separately.
- Skipping `--repair` after manual `uv tool install` → ORT version mismatch.

#### Troubleshooting

| Symptom | Fix |
|---------|-----|
| ORT / onnxruntime errors | `scubiee setup --repair` |
| Hangs on Windows iGPU | `scubiee setup --repair --profile cpu` |
| Globally stopped | `scubiee resume` then setup, or `setup --repair` |

**Exit:** 0 success, 1 failure.

#### Common questions — `setup`

**Q: Do I run setup for every repo?**  
No. Once per **machine**. Repos use `init`.

**Q: Setup finished but init says `machine_not_setup`.**  
Check `scubiee setup --status` — if empty, re-run `setup --repair`. Ensure you're calling the same scubiee binary (`scubiee --version --verbose`).

**Q: Can I run setup while globally stopped?**  
Only `setup --repair` (auto-resumes). Plain `setup` is blocked until `resume`.

**Q: How long does first setup take?**  
~5–15 minutes depending on model download and GPU calibration. `--skip-model` is for advanced/testing only.

---

### `scubiee preflight [path]`

**Purpose:** Fast dependency check before indexing or CI — faiss, rapidfuzz, semantic backend.

| Arg/flag | Default | Description |
|----------|---------|-------------|
| `path` | `.` | Repo context (some checks are repo-aware) |
| `--lexical-only` | false | Don't require embedding backend |

**Use when:** CI gate, or verifying install without running full `doctor`.

**Exit:** 0 if report `ok`, else 1.

---

### `scubiee resources`

**Purpose:** Show hardware snapshot + **live** CPU/RAM pressure and adaptive budgets (ResourceManager).

| Flag | Description |
|------|-------------|
| `--refresh` | Force re-detect hardware |
| `--save` | Persist snapshot to `hardware.json` |
| `--reset-rm` | Reset ResourceManager singleton (tests) |

**Use when:** Daemon seems slow or indexing pauses — check if RAM pressure throttled embed.

**Exit:** always 0.

---

## Project lifecycle

These commands manage **layer 3** — which repos are enrolled, paused, indexed, or removed.

---

### `scubiee init [path]` ⭐ Primary enrollment command

**Purpose:** Enroll a repository under Scubiee and index it. This is what most users should run (not raw `initialize` or `register` unless you know why).

**Prerequisites:** `scubiee setup` completed (`accel.json` exists).

#### Parameters

| Arg/flag | Default | Description |
|----------|---------|-------------|
| `path` | `.` | Repository root |
| `--no-index` | false | Enroll in registry without indexing |
| `--allow-once` | false | Don't persist always-allow consent |
| `--fast` | false | Index `.py` under fast roots only |
| `--roots` | — | Comma-separated roots (implies `--fast`) |
| `--confirm` | false | Bypass safety gate; skip interactive y/n |

#### What happens (step-by-step)

1. **Check machine setup** — fails if no `accel.json`.
2. **Preflight scope** — count indexable files; prompt or require `--confirm` if risky.
3. **Interactive confirm (TTY)** — shows file count + ETA; user confirms (unless `--confirm`).
4. **`initialize_repo`** — assign/read `project_id`, update registry, run index pipeline.
5. **Progress UI** — InitProgress bar; parse logs suppressed on TTY to avoid garbled output.
6. **Repeat init** — if already enrolled, uses incremental sync instead of full re-index.

#### On disk after success

| Artifact | Location |
|----------|----------|
| Project id | `<repo>/.scubiee/id.json` |
| Registry entry | `~/.scubiee/registry.json` |
| Index store | `~/.scubiee/projects/<ce_id>/` |
| VectorDB collection | Under `~/.scubiee/vectordb/` |

#### What init does NOT do

- Does **not** write Cursor MCP config → run `scubiee connect --cursor`.
- Does **not** replace global stop → if stopped, run `resume` first.

#### Examples

```bash
# Standard
cd ~/projects/my-app
scubiee init .

# Monorepo — index packages/ only
scubiee init . --fast --roots packages,src

# CI — non-interactive
scubiee init /repo --confirm --fast --roots packages

# Register only (no embed)
scubiee init . --no-index
```

#### Common mistakes

| Mistake | Reality |
|---------|---------|
| "I ran init but agent doesn't use Scubiee" | Need `connect` + MCP reload |
| "init wants confirm every time" | Use `--confirm` in scripts or narrow `--roots` |
| "I paused the repo, ran resume" | Per-repo pause needs **`activate`**, not `resume` |

**Exit:** 0 ok, 1 error, 2 safety pause, 0 if user cancels TTY prompt.

#### Common questions — `init`

**Q: Does init connect Cursor?**  
No. Always run `scubiee connect --cursor` (or your tool) after init, then reload MCP.

**Q: I ran init twice — will it re-index everything?**  
Second init on same enrolled repo uses **incremental sync**, not full rebuild (unless corruption/force paths).

**Q: What's the difference between `--fast` and full index?**  
`--fast` indexes only `.py` files under standard code roots (`packages`, `src`, …) or your `--roots`. Full index walks more file types with skip rules for `node_modules`, `.git`, etc.

**Q: Why did init exit 2 in CI?**  
Safety gate — pass `--confirm` or narrow scope with `--fast --roots`.

---

### `scubiee register [path]`

**Purpose:** Lower-level registration — same consent pipeline as MCP `register_project`. Used when MCP or CLI registers without full `init` UX.

| Flag | Description |
|------|-------------|
| `--always-allow` | Skip future MCP registration prompts |
| `--no-index` | Registry + id only |
| `--fast` / `--force` | Fast roots / force reindex |
| `--confirm` | Safety gate bypass |

**When to use:** Automation mirroring MCP consent, or tooling that splits register vs index.

**Prefer `init`** for human first-time enrollment (better prompts and progress).

---

### `scubiee initialize [path]`

**Purpose:** Managed init + reconcile **existing** index. Called internally by `init`; exposed for advanced/lifecycle tooling.

Same flags as documented for init subset: `--no-index`, `--allow-once`, `--confirm`.

**Difference from init:** No branded InitProgress UX, no repeat-init detection UX — thinner wrapper around `initialize_repo`.

---

### `scubiee activate [path]`

**Purpose:** Set repo state to **active**. Since 0.3.11, also **un-pauses** a per-repo paused repo.

**When:** After `scubiee pause .`, or when dashboard/ registry shows paused state.

```bash
scubiee activate .
scubiee sync-now .    # Now allowed again
```

**Not for global stop** — use `scubiee resume`.

---

### `scubiee pause [path]`

**Purpose:** Pause background indexing/sync for **one repo**. Engine and MCP stay up for other repos.

| Flag | Description |
|------|-------------|
| `--reason` | Stored in registry for audit |

**Effects:**

- Registry `state` → paused
- `sync-now` **blocked** for this repo
- Index data **kept** on disk
- MCP still connected — agent may still query existing index

**Use when:** Maintenance on one repo, reduce load, debugging index issues.

---

### `scubiee resume`

**Purpose:** **Global only** — reverse `scubiee stop`. Re-enables MCP configs, restores GATE rules, reconciles enrolled repos, brings engine back.

**No `path` argument.**

```bash
scubiee stop -y        # Global stop
scubiee resume         # Restore — NOT scubiee engine start
```

After resume, if MCP still broken: `scubiee connect --cursor` and reload IDE.

---

### `scubiee sync-now [path]`

**Purpose:** Lifecycle **freshness reconciliation** — daemon-oriented sync path (not the same as incremental `sync` but related).

| Flag | Description |
|------|-------------|
| `--confirm` | Large-tree safety |

**Blocked when repo is paused** — message tells you to `activate` first.

---

### `scubiee rebuild [path]`

**Purpose:** Force **full** index rebuild — ignores incremental merkle diff, re-embeds everything.

**When:** Corrupt index, model change, doctor recommends rebuild, after `--reindex` upgrade flag.

**Cost:** Same time as initial index — can take minutes on large repos.

---

### `scubiee remove [path]`

**Purpose:** Remove repo from lifecycle **registry** only — lightweight unmanage.

| Flag | Description |
|------|-------------|
| `--delete-store` | Also delete `~/.scubiee/projects/<id>/` |

**Does NOT remove:** VectorDB collections, `<repo>/.scubiee/`, repo MCP/rules files.

**Prefer `wipe . --confirm`** for complete single-repo cleanup.

---

### `scubiee never-index [path]`

**Purpose:** Permanent block — Scubiee will refuse to index this path until block cleared.

| Flag | Description |
|------|-------------|
| `--reason` | Audit string |

**Use when:** Vendor mirrors, read-only snapshots, paths that must never be enrolled.

---

### `scubiee list`

**Purpose:** JSON list of all managed repos — paths, ids, states, pause reasons.

**Use when:** Multi-repo machine, verifying wipe removed enrollment, support tickets.

**Exit:** 0.

---

## Index & search

---

### `scubiee index [path]`

**Purpose:** Run full index pipeline; **always registers** project (even if you only wanted re-index — consider `rebuild` for enrolled repos).

#### Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `--force` | false | Force full re-index |
| `--bits` | `8` | TurboQuant bits (8 recommended; 4 hurts quality) |
| `--model` | `nomic-ai/CodeRankEmbed` | Embedding model |
| `--fast` | false | `.py` under fast roots only |
| `--roots` | — | Comma-separated (implies `--fast`) |
| `--confirm` | false | Safety gate |

**Note:** `--roots` without `--fast` auto-enables fast mode.

#### Pipeline (what “index” means)

```text
Files → Merkle → Tree-sitter parse → Graph → Chunks → Embed → FAISS + lexical
```

Stored under `~/.scubiee/projects/<project_id>/`.

**Exit:** 0 ok, 1 error/deferred, 2 confirm required.

---

### `scubiee sync [path]`

**Purpose:** **Incremental** update — only changed files since last merkle snapshot.

**Daemon preference:** If engine healthy, sync goes through HTTP so search generation updates atomically. Falls back to local sync + publish notify.

| Flag | Description |
|------|-------------|
| `--confirm` | Large delta safety |

**When to run:** After `git pull`, switching branches, or when agent misses recent edits.

**Exit:** 0 success/up-to-date, 1 error, 2 confirm required.

---

### `scubiee search <query> [path]`

**Purpose:** Hybrid semantic + lexical search from terminal (same engine as MCP).

| Arg/flag | Default | Description |
|----------|---------|-------------|
| `query` | required | Natural language or keywords |
| `path` | `.` | Repo root |
| `--top-k` | `8` | Max hits |
| `--local` | false | Skip daemon; in-process index |
| `--url` | `http://127.0.0.1:8765` | Daemon URL |

**Argument order flexibility:** `search "query" .` and `search . "query"` both work.

**Fallback:** If daemon unreachable, CLI tries local index once before failing.

Example JSON hit:

```json
{
  "latency_ms": 42.3,
  "hits": [
    {
      "rank": 1,
      "file": "packages/pipeline/searcher.py",
      "score": 0.87,
      "chunk_id": "…",
      "preview": "…",
      "source": "semantic"
    }
  ]
}
```

---

### `scubiee status [path]`

**Purpose:** Full enrollment + index + freshness + daemon health snapshot.

| Flag | Description |
|------|-------------|
| `--url` | Engine health URL |
| `--json` | Force JSON on TTY |

**Unmanaged repo output:**

```json
{
  "enrolled": false,
  "state": "unmanaged",
  "hint": "Run `scubiee init .` to enroll this repository."
}
```

**Key fields when enrolled:** `chunks`, `freshness`, `server.ok`, `state` (active/paused).

---

### `scubiee gate [path]`

**Purpose:** Tiny managed check (~5 tokens) — same logic MCP `gate()` uses locally.

Prints one line to stdout, e.g. managed/ready state. **No daemon required.**

**Use when:** Scripts checking enrollment before calling MCP.

---

## Diagnostics & certification

---

### `scubiee doctor [path]`

**Purpose:** Comprehensive readiness report — install identity, daemon, index, MCP, duplicate PATH installs, safe fixes.

| Flag | Description |
|------|-------------|
| `--all` | Every managed repo |
| `--fix` | Apply **safe** repairs only (never pip install, rebuild, Forget) |

#### What doctor checks (conceptual)

- Active vs expected scubiee binary (duplicate install detection)
- Faiss / fastembed / ORT health
- Daemon reachable
- Repo enrolled and index present
- MCP config present for connected tools
- Migration needed?

#### When to run

| Situation | Command |
|-----------|---------|
| Anything broken | `scubiee doctor .` |
| After upgrade | `scubiee doctor . --fix` |
| Multi-repo machine | `scubiee doctor --all` |

**Exit:** 0 if report `ok`, else 1.

---

### `scubiee certify [path]`

**Purpose:** Release certification gate — pytest-style checks for shipping quality.

| Flag | Description |
|------|-------------|
| `--skip-daemon` | Skip daemon health checks |
| `--canary` | Include warm semantic canary query |

**Use when:** CI release pipeline, pre-publish validation.

---

### `scubiee test [tier] [path]`

**Purpose:** Run named verification tier; **always JSON** output.

| Tier | Scope |
|------|-------|
| `quick` | Fast smoke (default) |
| `core` | Core pipeline tests |
| `fault` | Fault injection |
| `install` | Install layout |
| `clients` | External client suites |
| `all` | Everything |

| Flag | Description |
|------|-------------|
| `--clients` | Allow client suites if client installed |

**Note:** Requires pytest in same Python env — mainly for git checkouts / dev machines.

---

### `scubiee diagnose`

**Purpose:** Installation diagnostics + **shareable log file** for support.

| Flag | Description |
|------|-------------|
| `--no-tests` | Skip embedded test suite |
| `--desktop` | Write `Desktop/scubiee-diagnose.json` |
| `--output` | Custom path |

Report includes: version, platform, acceleration, capabilities, daemon verdict, test results.

---

## Engine, serve & dashboard

Default engine: **`http://127.0.0.1:8765`**

The engine holds per-repo runtimes, serves search/grep to MCP, and runs background sync. Logs: `~/.scubiee/engine.log`, `~/.scubiee/watchdog.log`.

---

### `scubiee engine <action> [path]`

#### Actions explained

| Action | What it does | When to use |
|--------|--------------|-------------|
| `start` | Start daemon + watchdog; set desired RUN | Manual start after `engine stop` |
| `stop` | Stop daemon + watchdog; set STANDBY | Free RAM; MCP still works (may cold-start) |
| `status` | Health, pause state, watchdog | Debugging |
| `run` | Foreground server (blocks terminal) | Dev/debug |
| `ensure` | Start only if down (idempotent) | Scripts |
| `watchdog` | Foreground watchdog loop | Internal |
| `supervisor` | Logon supervisor loop | OS session lifecycle |
| `autostart` | Register/unregister logon task | `--off` to disable |

#### Shared flags

| Flag | Default | Applies to |
|------|---------|------------|
| `path` | `.` | start, run, status, ensure |
| `--host` | `127.0.0.1` | start, run |
| `--port` | `8765` | start, run |
| `--wait` | `90.0` | start — seconds to wait for /health |
| `--no-open` | false | run — skip browser open |
| `--logon` | false | supervisor |
| `--off` | false | autostart unregister |

#### `engine stop` vs `scubiee stop` (critical)

| | `engine stop` | `scubiee stop` |
|--|---------------|----------------|
| Daemon | Stopped | Stopped |
| MCP configs | **Kept** | **Removed/stubbed** |
| Rules | **Kept** | **Removed** |
| Resume | `engine start` or first MCP call | **`scubiee resume`** only |
| Repo `.scubiee` | Kept | Removed on global stop |

#### Globally stopped behavior

- `engine start` / `ensure` / `run` → **blocked** — use `scubiee resume`
- `engine stop` → OK with hint (already stopped)
- `engine status` → allowed; shows `globally_paused`

---

### `scubiee serve [path]`

**Purpose:** Alias for **foreground** daemon — same as `engine run`. Blocks until killed.

| Flag | Default |
|------|---------|
| `--host` | `127.0.0.1` |
| `--port` | `8765` |

---

### `scubiee dashboard [action]`

**Purpose:** Localhost operator UI — repo list, health, Forget button, settings.

| Invocation | Behavior |
|------------|----------|
| `scubiee dashboard` | Start + open browser |
| `scubiee dashboard --no-open` | Start without browser |
| `scubiee dashboard --status` | URL, PID, health JSON |
| `scubiee dashboard stop` | Stop dashboard process |

**Forget vs wipe:** Dashboard Forget removes registry + index store with confirmation. Full cleanup of VectorDB + `.scubiee` + repo MCP → use **`wipe . --confirm`**.

---

## Global stop, halt & unlock

Three different ways to “stop” things — **do not confuse them**.

```text
scubiee engine stop     → daemon only, MCP stays
scubiee pause .         → one repo indexing paused
scubiee stop            → global: MCP off, rules off, .scubiee removed from repos
scubiee halt            → kill processes + MCP stub (pre-wipe/upgrade)
```

---

### `scubiee stop`

**Purpose:** **Global stop** — user intentionally disables Scubiee machine-wide.

**What it does:**

1. Confirms (TTY unless `-y`)
2. Stubs/removes MCP entries
3. Hides GATE rules
4. Removes repo `.scubiee` folders (enrollment markers)
5. Kills scubiee processes
6. Sets global paused flag

**Data kept:** Index stores under `~/.scubiee/projects/` (until wipe), accel profile, models.

| Flag | Description |
|------|-------------|
| `-y`, `--yes` | Skip confirmation |

**Resume:** `scubiee resume` — then `connect` if MCP not restored.

---

### `scubiee halt [path]`

**Purpose:** **Safe shutdown** before wipe or upgrade while Cursor/Claude stay open.

**What it does:**

1. Rewrites MCP to **no-op** stub (IDEs respawn harmless process)
2. Kills Scubiee engine/MCP processes
3. Releases file locks

| Arg | Default | Description |
|-----|---------|-------------|
| `path` | `.` | Repo for project MCP pin context |

**Next steps (printed):** `scubiee wipe --all --confirm` OR reinstall package.

---

### `scubiee unlock-tool`

**Purpose:** **Windows** — free `%APPDATA%\uv\tools\scubiee` when `uv tool install` fails with Access denied.

**Flow:** disable MCP → stop processes → force-remove / rename tool dir.

**No arguments.**

**Typical sequence:**

```bash
scubiee unlock-tool
uv tool install --force scubiee --index-url https://pypi.org/simple
scubiee setup --repair
scubiee connect --cursor
```

Admin privileges **do not** fix this — it's file locks from running Python, not ACLs.

---

## Connect & disconnect

**Layer 4** — tells IDEs how to spawn MCP and teaches agents to use Scubiee tools.

---

### Global vs workspace-local MCP

| Tool type | Connect once globally? | Need per-repo connect? |
|-----------|------------------------|-------------------------|
| Cursor, Claude Code, Codex, Continue, Zed, OpenCode, Amp, Pi | Yes (user config) | Cursor also gets **project** `.cursor/mcp.json` |
| Kiro, Copilot, Cline, Roo Code (“Special-4”) | User config yes | **Must** run connect **inside each repo** for workspace MCP |

**Why project MCP exists:** Cursor global MCP cannot reliably expand `${workspaceFolder}` — project pin sets absolute `CTX_REPO`.

---

### Supported tool slugs

CLI flag: `--<slug>` (hyphens OK: `--claude-code`, `--roo-code`).

| Slug | Tool | Config locations (summary) |
|------|------|----------------------------|
| `cursor` | Cursor | `~/.cursor/mcp.json`, `~/.cursor/rules/scubiee.mdc`, `<repo>/.cursor/mcp.json` |
| `claude-code` | Claude Code | `~/.claude.json`, append `~/.claude/CLAUDE.md` |
| `codex` | Codex | `~/.codex/config.toml`, `~/.codex/AGENTS.md` |
| `kiro` | Kiro | `~/.kiro/…`, `<repo>/.kiro/settings/mcp.json` |
| `devin-desktop` | Devin Desktop | `<repo>/.devin/mcp_config.json` |
| `windsurf` | *(alias → devin-desktop)* | Backward compat |
| `copilot` | VS Code / Copilot | User mcp + Copilot CLI + `<repo>/.vscode/mcp.json` |
| `cline` | Cline | VS Code globalStorage + CLI + `<repo>/.cline/mcp.json` |
| `roo-code` | Roo Code | VS Code globalStorage + `<repo>/.roo/mcp.json` |
| `continue` | Continue | `~/.continue/config.yaml` |
| `zed` | Zed | Platform-specific Zed settings |
| `opencode` | OpenCode | `~/.config/opencode/opencode.json` |
| `amp` | Amp | `~/.config/amp/settings.json` |
| `pi` | Pi | `~/.pi/agent/mcp.json` |

Full path table: [Data & files reference](./data-and-files-reference.md).

---

### `scubiee connect`

**Purpose:** Write MCP configs + GATE rules; record tools in `~/.scubiee/connected_tools.json`; fan out to enrolled repos.

| Flag | Description |
|------|-------------|
| `--<slug>` | Per-tool connect |
| `--all` | All tools in registry |
| `--dry-run` | Print paths that would change — no writes |
| `--repo PATH` | Project folder for workspace-local MCP (default: cwd) |

**Requires:** At least one of `--all` or a tool flag.

**Auto-resumes** if globally stopped.

**After connect:** Reload MCP in IDE (Cursor: Settings → MCP → reload).

```bash
scubiee connect --cursor
scubiee connect --all --dry-run
cd ~/projects/foo && scubiee connect --copilot --repo .
```

**Exit:** 0 if all selected tools ok, 1 if any failed or none selected.

#### Common questions — `connect`

**Q: I ran connect once globally — why doesn't Kiro/Copilot work in my repo?**  
Special-4 tools need **workspace-local** MCP. `cd` into the repo and run connect again (or use `--repo /path`).

**Q: Does connect start the engine?**  
Not directly — but MCP spawn or `resume` may start it. Verify with `scubiee engine status`.

**Q: What does `--dry-run` show?**  
Exact file paths that would be written — use before first connect on a shared machine.

**Q: Connect after `scubiee stop` — do I still need resume?**  
Connect **auto-resumes** when globally stopped. If restore fails, run `resume` explicitly.

---

### `scubiee disconnect`

**Purpose:** Remove MCP entries and rules for selected tools.

| Flag | Description |
|------|-------------|
| `--<slug>` / `--all` | Tools to disconnect |
| `--dry-run` | Preview only |
| `--repo PATH` | Limit workspace cleanup to one repo |
| `--all-workspaces` | Clean project MCP on **every** enrolled repo (default when `--repo` omitted) |

**Exit:** 0 if all ok, else 1.

---

## Upgrade & migrate

---

### `scubiee upgrade`

**Purpose:** One-command upgrade supervisor — PyPI swap, quiesce processes, migrations, MCP/rules rebind, daemon restart, health check.

#### Parameters

| Flag | Description |
|------|-------------|
| `--pre` | Allow pre-release versions from PyPI |
| `--check` | **Plan only** (DiffPlan JSON) — no swap, no migrations |
| `--no-connect` | Skip MCP/GATE rewrite on enrolled repos |
| `--repair` | Also refresh accel/setup packages post-upgrade |
| `--reindex` | Force full embed rebuild even if ABI unchanged |

#### Step-by-step (normal upgrade)

1. Check PyPI for newer version
2. **Quiesce** — halt/stop processes, unlock Windows file locks if needed
3. **Package swap** — `uv tool install` / pip equivalent (skipped if already latest unless post-steps requested)
4. **Migrate** — schema/data migrations per managed project
5. **Rebind** — rewrite MCP + rules on enrolled repos (unless `--no-connect`)
6. **Daemon restart** — start engine + health probe with retries
7. Print plan actions + next steps

#### When already on latest PyPI

Still runs post-upgrade refresh (daemon, migrations, rebind) unless `--check`.

#### Windows file lock failure

JSON may include `quiesce_failed`. Run:

```bash
scubiee unlock-tool
scubiee upgrade
```

**Exit:** 0 if `result.ok`, else 1.

#### Common questions — `upgrade`

**Q: Should I use `uv tool install --force` or `scubiee upgrade`?**  
Prefer **`scubiee upgrade`** — it quiesces processes, migrates data, rebinds MCP, and health-checks. Manual uv install alone skips migrations/rebind.

**Q: Upgrade says already latest — anything to do?**  
Post-steps still refresh daemon/MCP unless `--check`. Run `connect` + reload IDE if MCP acts stale.

**Q: When do I need `--reindex`?**  
When search quality breaks after embed model/ABI change, or support asks for full rebuild. Destructive — re-embeds all repos.

**Q: Upgrade failed with quiesce — Cursor is open.**  
Run `scubiee halt`, then `unlock-tool` on Windows, then retry upgrade.

---

### `scubiee migrate [path]`

**Purpose:** Check or apply **data schema migrations** after version jumps.

| Flag | Description |
|------|-------------|
| `path` | Single project (default `.`) |
| `--apply` | Apply for one repo |
| `--apply-all` | Apply all managed projects |
| `--check-all` | Check all without applying |
| `--force` | Force migration even if schema looks current |

**When:** After manual `uv tool install`, or if doctor reports migration needed.

---

## Settings & wipe

---

### `scubiee settings`

**Purpose:** Read/write `~/.scubiee/prefs.json` — registration mode and indexing behavior.

| Flag | Description |
|------|-------------|
| `--show` | Print prefs (default if no changes) |
| `--mode automatic` | Auto-register repos when opened |
| `--mode mcp_cli` | Require consent on first MCP use |
| `--incremental true/false` | Incremental keeper after register |
| `--watching true/false` | File watching / keeper |

```bash
scubiee settings --show
scubiee settings --mode mcp_cli
```

---

### `scubiee wipe [path]`

**Purpose:** Destructive cleanup — single repo or entire machine.

#### Single-repo wipe (`scubiee wipe . --confirm`)

**Removes:**

| Item | Location |
|------|----------|
| Registry enrollment | `registry.json` |
| Index store | `~/.scubiee/projects/<id>/` |
| VectorDB collections | Repo-linked |
| Repo identity | `<repo>/.scubiee/` |
| Repo MCP + rules | e.g. `.cursor/mcp.json`, rules under repo |

**Keeps:** Source code, global MCP (`~/.cursor/mcp.json`), other repos, accel/models.

**Re-enroll:** `scubiee init .` + `connect`

#### Full machine wipe (`scubiee wipe --all --confirm`)

Deletes essentially all Scubiee state — daemon, `~/.scubiee`, all tool MCP/rules, models (unless `--keep-models`), package (unless `--keep-package`).

| Flag | Description |
|------|-------------|
| `--confirm`, `--yes` | Required for non-interactive |
| `--keep-models` | Keep CodeRank/FastEmbed caches |
| `--keep-package` | Keep uv tool install |
| `--package` | Explicitly uninstall scubiee package |

#### Confirmation behavior

| Scenario | Behavior |
|----------|----------|
| TTY, no `--confirm` | Interactive Y/N |
| Non-TTY, no `--confirm` | Exit **2** |
| User declines TTY | Exit **0**, cancelled |

#### `remove` vs `wipe` (summary)

| | `remove` | `wipe --confirm` |
|--|----------|------------------|
| Registry | Yes | Yes |
| Index store | Optional (`--delete-store`) | Always |
| VectorDB | No | Yes |
| `.scubiee/` in repo | No | Yes |
| Repo MCP/rules | No | Yes |
| Confirmation | No | Yes |

#### Common questions — `wipe`

**Q: Will wipe delete my source code?**  
**Never.** Wipe removes Scubiee metadata, indexes, and tool configs — not your project files.

**Q: Single-repo wipe vs `--all`?**  
`wipe . --confirm` = one repo. `wipe --all --confirm` = entire machine (all repos, models, MCP, optional package uninstall).

**Q: Why exit 2 in my script?**  
Missing `--confirm`. Wipe requires explicit confirmation in non-interactive mode by design.

**Q: Wipe left `audit.remaining` paths on Windows.**  
File locks — quit IDE, `scubiee halt`, re-run wipe. See [JSON glossary — wipe](#scubiee-wipe--field-glossary).

---

## MCP adapter (CLI)

### `scubiee mcp [path]`

**Purpose:** Stdio MCP server process — **IDE launches this**, not you.

Sets `CTX_REPO` if path provided; forwards JSON-RPC to engine via `pipeline.mcp_locate`.

**Agent tools (not CLI commands):** `gate`, `status`, `map`, `focus`, `grep`, `glob`, `workspace`, `expand`, `register_project`.

Full parameter docs: [MCP tools reference](../docs/web-info/mcp-tools-reference.md).

**Session start for agents:**

1. Call `gate()` or `status()` once
2. If `managed: true` and `ok: true` → use Scubiee for discovery
3. If `warming: true` → retry **locate tool** once after few seconds — don't poll status every turn

---

## Command relationships (which to use when)

### Enrollment: `init` vs `register` vs `initialize`

| Command | Audience | UX |
|---------|----------|-----|
| **`init`** | Humans, first time | Progress bar, prompts, repeat-init handling |
| `register` | MCP parity / scripts | Thin registration API |
| `initialize` | Internal/advanced | Same core as init without UX |

### Indexing: `index` vs `sync` vs `sync-now` vs `rebuild`

| Command | Scope | Incremental? |
|---------|-------|--------------|
| `index` | Full pipeline + register | No (full walk) |
| `sync` | Changed files only | Yes |
| `sync-now` | Lifecycle freshness pass | Daemon-oriented |
| `rebuild` | Force full re-index | No |

**Rule:** Daily edits → `sync`. Corruption / model change → `rebuild`. First time → `init`.

### Stop: `engine stop` vs `pause` vs `stop` vs `halt`

See [Global stop, halt & unlock](#global-stop-halt--unlock).

### Cleanup: `remove` vs `wipe` vs dashboard Forget

| Method | Completeness |
|--------|--------------|
| `remove` | Registry only (minimal) |
| Dashboard Forget | Registry + index store (with id confirm) |
| **`wipe . --confirm`** | Full repo Scubiee data cleanup |

---

## Lifecycle decision matrix

| Goal | Command | Notes |
|------|---------|-------|
| First-time machine setup | `scubiee setup` | Once per machine |
| Enroll + index a repo | `scubiee init .` | Then `connect` |
| Wire Cursor/IDE | `scubiee connect --cursor` | Reload MCP |
| Pause indexing one repo | `scubiee pause .` | MCP stays |
| Resume one repo | `scubiee activate .` | **Not** `resume` |
| Stop everything (MCP off) | `scubiee stop` | Then `resume` |
| Stop daemon only | `scubiee engine stop` | MCP stays |
| Start daemon | `scubiee engine start` | Or first MCP call |
| Unmanage repo fully | `scubiee wipe . --confirm` | Index + `.scubiee` + rules |
| Unmanage registry only | `scubiee remove .` | Rare |
| Uninstall Scubiee entirely | `scubiee wipe --all --confirm` | `--keep-models` optional |
| Fix broken deps | `scubiee setup --repair` | |
| Upgrade version | `scubiee upgrade` | Then connect + doctor |
| Windows file lock | `scubiee unlock-tool` | Then reinstall |
| Pre-wipe safe stop | `scubiee halt` | Cursor can stay open |
| Check enrollment (tiny) | `scubiee gate .` | ~5 tokens |
| Manual search | `scubiee search "…" .` | Same engine as MCP |

---

## Commands allowed when globally stopped

| Allowed | Blocked (examples) |
|---------|-------------------|
| `doctor`, `preflight`, `diagnose`, `gate`, `list` | `init`, `index`, `search`, `sync` |
| `resume`, `stop`, `halt`, `unlock-tool`, `wipe` | `engine start`, `engine ensure`, `engine run` |
| `connect`, `disconnect`, `upgrade` | `setup` (except `--repair`) |
| `engine status` | Most other commands |

Help (`-h` / `--help`) always works.

---

## Full command index

| Subcommand | One-line summary |
|------------|------------------|
| `index` | Full index pipeline |
| `resources` | Hardware + live pressure |
| `test` | Verification tiers |
| `preflight` | Dependency check |
| `doctor` | Readiness + safe fix |
| `certify` | Release gate |
| `register` | MCP-style registration |
| `initialize` | Managed init (advanced) |
| `activate` | Unpause / activate repo |
| `pause` | Per-repo pause |
| `resume` | Global resume |
| `sync-now` | Freshness reconciliation |
| `rebuild` | Force full rebuild |
| `remove` | Registry-only unmanage |
| `never-index` | Permanent deny |
| `list` | Managed repos JSON |
| `settings` | prefs.json |
| `search` | Hybrid search |
| `status` | Enrollment + freshness |
| `gate` | Tiny managed check |
| `sync` | Incremental sync |
| `serve` | Foreground daemon |
| `dashboard` | Operator UI |
| `engine` | Daemon control |
| `mcp` | MCP stdio adapter |
| `init` | **Primary enroll + index** |
| `setup` | **Primary machine install** |
| `wipe` | Destructive cleanup |
| `stop` | Global stop |
| `halt` | Safe process kill |
| `unlock-tool` | Windows lock release |
| `migrate` | Schema migration |
| `diagnose` | Support log bundle |
| `connect` | IDE MCP + rules |
| `disconnect` | Remove MCP + rules |
| `upgrade` | Package upgrade supervisor |

---

## JSON output glossaries

When stdout is **not a TTY** (piped, CI, scripts), most commands emit JSON. This section explains **what each field means** and **what to do when it looks wrong**.

Tip: force JSON on TTY for some commands: `scubiee status . --json`.

---

### `scubiee doctor .` — field glossary

Doctor is the **single best JSON blob** for support. Top-level `"ok": true` means: capabilities OK, index usable, manifest valid, no blocking repair items.

#### Example (abbreviated)

```json
{
  "ok": false,
  "repo": "C:\\dev\\my-app",
  "project_id": "ce_223fe983ee19e5629ce88102e6581038",
  "install": {
    "version": "0.3.14",
    "python": "C:\\Users\\you\\AppData\\Roaming\\uv\\tools\\scubiee\\Scripts\\python.exe",
    "active_binary": "C:\\…\\scubiee.exe",
    "expected_binary": "C:\\…\\scubiee.exe",
    "binaries_match": true,
    "extra_on_path": [],
    "multiple_installs": false,
    "hint": null
  },
  "enrollment": { "enrolled": true },
  "capabilities": { "ok": true, "missing_required": [] },
  "accel": {
    "preferred_profile": "dml",
    "active_profile": "dml",
    "backup_reason": null,
    "recommended_command": "scubiee engine ensure ."
  },
  "readiness": {
    "index_usable": true,
    "manifest": { "ok": true },
    "soft_search_ready": true,
    "embed_profile": "dml",
    "embed_batch": 32,
    "embed_tps": 120.5
  },
  "binding": { "ok": true },
  "journal": { "pending": false, "paths": [] },
  "git_family": { "needs_reconcile": false },
  "connect_registry": { "ok": true, "warnings": [] },
  "repair_plan": [
    { "id": "bind_daemon", "kind": "safe", "detail": "scubiee engine ensure ." }
  ],
  "repairs": ["scubiee engine ensure ."],
  "checked_at": 1735689600.0
}
```

#### Field reference

| Field | Meaning | If wrong |
|-------|---------|----------|
| `ok` | Overall pass (excludes non-blocking daemon bind hints) | Read `repair_plan` |
| `project_id` | Stable `ce_…` id | `null` → not enrolled → `init` |
| `install.binaries_match` | Invoked binary matches this Python’s scubiee | Fix PATH; use one install (uv tool) |
| `install.multiple_installs` | Duplicate scubiee on PATH | Uninstall conda/pip copy; keep uv tool |
| `install.hint` | Human explanation of install drift | Follow hint text |
| `enrollment.enrolled` | Repo has bound project id | `false` → `scubiee init .` |
| `enrollment.repair` | Suggested fix when not enrolled | Usually `scubiee init .` |
| `capabilities.ok` | faiss, rapidfuzz, semantic backend | `setup --repair` |
| `capabilities.missing_required` | List of missing deps | `setup --repair` |
| `readiness.index_usable` | Index store loadable + searchable | `rebuild` or `init` |
| `readiness.manifest.ok` | Publication manifest valid | `false` → corrupt index → `rebuild` |
| `readiness.soft_search_ready` | Index + capabilities both OK | Fix whichever sub-field is false |
| `binding.ok` | Daemon can bind this workspace | `engine ensure .` (safe repair) |
| `journal.pending` | Dirty journal needs replay | `doctor . --fix` |
| `git_family.needs_reconcile` | Duplicate worktree indexes | `doctor . --fix` |
| `connect_registry.warnings` | MCP/registry mismatches | Often `connect` or `init` on stale path |
| `repair_plan[].kind` | `safe` = `--fix` applies; `manual` = you run command | See `detail` |
| `meta.chunks` | Indexed chunk count | 0 → index empty or not built |

**`doctor --all`:** wraps per-repo reports in `"repositories": [...]` plus merged `"repair_plan"`.

**`doctor . --fix`:** returns `"applied"`, `"manual"`, `"before"`, `"after"` — only **safe** repairs run automatically.

---

### `scubiee status .` — field glossary

Status answers: *Is this folder enrolled? Is the index warm? Is the daemon up? Is the tree stale?*

#### Unmanaged repo

```json
{
  "root": "C:\\dev\\random-folder",
  "enrolled": false,
  "state": "unmanaged",
  "project_id": null,
  "hint": "Run `scubiee init .` to enroll this repository."
}
```

**Explanation:** No `<repo>/.scubiee/id.json` and no registry binding. Agent MCP will show `managed: false`. This is normal for folders you never initialized.

#### Enrolled repo (key fields)

| Field | Meaning |
|-------|---------|
| `enrolled` | `true` when managed |
| `state` | `active`, `paused`, `unmanaged`, etc. |
| `store` | Path to `~/.scubiee/projects/<id>/` |
| `collection` | VectorDB collection name |
| `chunks` | Number of indexed chunks |
| `vectors` | Vector index stats (dim, count) |
| `merkle_files` | Files tracked for incremental sync |
| `freshness.clean` | `true` if index matches disk (Merkle) |
| `freshness.changed_count` | Files needing sync |
| `freshness.strategy` | `none`, `incremental`, `background`, `full` |
| `freshness.added/modified/removed` | Sample paths (capped at 50) |
| `server.ok` / `server.warm` | Daemon health from `/health` |
| `vectordb.collections` | All collections on machine |

**When `freshness.clean` is false:** Run `scubiee sync .` — index is behind git/disk.

**When `server.ok` is false but enrolled:** Run `scubiee engine ensure .` or open IDE (MCP may start daemon).

---

### `scubiee upgrade` — field glossary

Upgrade JSON is the **audit trail** for version jumps. Use `scubiee upgrade --check` to preview without applying.

#### Example plan (`--check`)

```json
{
  "ok": true,
  "check_only": true,
  "old_version": "0.3.13",
  "target_version": "0.3.14",
  "new_version": "0.3.14",
  "platform": "windows",
  "revision_id": "a1b2c3d4e5f6",
  "pypi": {
    "latest": "0.3.14",
    "current": "0.3.13",
    "update_available": true
  },
  "plan": {
    "from_version": "0.3.13",
    "to_version": "0.3.14",
    "release_path": ["0.3.14"],
    "actions": [
      { "component": "package", "action": "swap", "reason": "0.3.13 → 0.3.14", "destructive": false },
      { "component": "mcp_pins", "action": "rewrite", "reason": "pin format v2", "destructive": false },
      { "component": "embeddings", "action": "skip", "reason": "ABI unchanged", "destructive": false }
    ],
    "warnings": []
  },
  "phases": ["detect", "plan"],
  "next_steps": ["Run `scubiee upgrade` to apply this plan."]
}
```

#### Component actions (plan.actions)

| component | Typical action | Meaning |
|-----------|----------------|---------|
| `package` | `swap` | PyPI / uv tool install new version |
| `daemon` | `restart` | Engine restart after swap |
| `index_schema` | `migrate` | On-disk index schema migration |
| `embeddings` | `rebuild` | **Destructive** — full re-embed (use `--reindex` to force) |
| `mcp_pins` | `rewrite` | Refresh MCP env in IDE configs |
| `gate_rules` | `rewrite` | Refresh agent rule files |
| `accel` | `repair` | Re-run setup packages |
| `home_layout` | `migrate` | Stamp home directory layout version |

#### Full upgrade result (additional fields)

| Field | Meaning | If failed |
|-------|---------|-----------|
| `quiesce.ok` | Processes stopped, locks released | `unlock-tool`, retry |
| `swap.ok` | Package swap succeeded | Check uv/pip error in `swap` |
| `migration.migrated` | Count of projects migrated | Re-run `migrate --apply-all` |
| `embeddings.destructive` | Full rebuild ran | Verify search; may take time |
| `daemon.action` | `started`, `already_running`, etc. | `engine start` |
| `rebind.ok` | MCP/rules rewritten on enrolled repos | `connect --cursor` manually |
| `rebind.repos` | List of repos refreshed | — |
| `health.ok` | Post-upgrade health probe | `doctor .`, reload MCP |
| `error` | `quiesce_failed`, `rebind_failed`, etc. | Read `hint` |
| `next_steps` | Human checklist | Follow in order |

**Already latest:** `swap.skipped: true`, but post-steps (daemon, rebind) may still run unless `--check`.

---

### `scubiee list` — field glossary

Each array element describes one managed repo:

| Field | Meaning |
|-------|---------|
| `project_id` | `ce_…` stable id |
| `root` / `primary_path` | Main checkout path |
| `paths` | All bound paths (worktrees) |
| `state` | `active`, `paused`, … |
| `paused` | Boolean shorthand |
| `presence` | `online`, `missing`, etc. (retention logic) |
| `indexed` / `has_index` | Index store usable |
| `index_state` | `ready` or `empty` |
| `forget_allowed` | Dashboard Forget eligibility |
| `store_dir` | `~/.scubiee/projects/<id>/` |

**Use case:** After `wipe`, confirm repo disappeared from list. After `pause`, see `paused: true`.

---

### `scubiee wipe` — field glossary

#### Confirm required (exit 2)

```json
{
  "ok": false,
  "warning": "confirm_required",
  "needs_confirm": true,
  "scope": "repo",
  "root": "C:\\dev\\my-app",
  "message": "Safety pause: repo wipe was not run…",
  "hint": "Re-run with: scubiee wipe C:\\dev\\my-app --confirm"
}
```

**Explanation:** Intentional safety — wipe never runs silently in scripts without `--confirm`.

#### Successful repo wipe

Look for `"ok": true`, `"scope": "repo"`, and action summaries (registry removed, store deleted, vectordb dropped).

#### Full wipe (`--all --confirm`)

| Field | Meaning |
|-------|---------|
| `scope` | `"all"` |
| `audit.clean` | `true` when no Scubiee artifacts remain |
| `audit.remaining` | Paths still on disk (common on Windows with locks) |
| `remaining_processes` | PIDs still running |
| `next` | Human next step (reinstall command or re-run wipe) |

**If `audit.remaining` non-empty:** Quit Cursor, run `scubiee halt`, re-run wipe.

---

### `scubiee diagnose` — field glossary

| Section | Contents |
|---------|----------|
| `platform` | OS, machine arch |
| `python` | Version, executable |
| `hardware` | CPU, RAM snapshot |
| `acceleration` | Profile, batch, stale_accel flag |
| `libraries` | faiss, onnxruntime, fastembed versions |
| `capabilities` | Same family as preflight |
| `index_status` | Managed projects summary |
| `daemon` | Reachable or not |
| `tests` | Quick test tier results (if not `--no-tests`) |
| `verdict.ok` | Overall pass |
| `verdict.capabilities` | `pass` / `FAIL` |
| `verdict.daemon` | `running` / `not running` |
| `log_file` | Path to saved JSON — **attach this to support** |

**Note:** Daemon not running does not always fail verdict — capabilities matter most for install issues.

---

### `scubiee stop` / `scubiee resume` — field glossary

#### `stop` success

| Field | Meaning |
|-------|---------|
| `paused_at` | Unix timestamp |
| `connected_tools` | Slugs remembered for resume |
| `teardown` | Per-tool MCP/rule removal results |
| `mcp_skip_warning` | Some MCP files had invalid JSON — manual fix |
| `hidden_scubiee_dirs` | Repo `.scubiee` folders hidden/removed |
| `process_warning` | Some processes may still run |

#### `resume` success

| Field | Meaning |
|-------|---------|
| `restored_id_files` | `.scubiee/id.json` restored in repos |
| `connect_restore` | Per-tool MCP reinstall results |
| `engine` | `ensure_daemon` result |
| `reconciled` | Background sync reconciliation |
| `connect_hint` | Shown if no tools were connected before stop |

**If `resume.ok` is false:** Scubiee stays stopped until MCP restore succeeds — fix errors, run `resume` again (do not use `engine start` alone).

---

### `scubiee connect` — result shape

Array of per-tool results (or object keyed by slug in some versions):

| Field | Meaning |
|-------|---------|
| `ok` | Tool connect succeeded |
| `slug` | Tool identifier |
| `paths_written` | Files created/updated |
| `errors` | Write failures (permissions, invalid existing JSON) |

Use `--dry-run` to preview `paths_written` without changes.

---

### `scubiee search` — result shape

| Field | Meaning |
|-------|---------|
| `latency_ms` | Round-trip time |
| `hits[].rank` | 1-based rank |
| `hits[].file` | Repo-relative path |
| `hits[].score` | Fusion score |
| `hits[].preview` | Text snippet |
| `hits[].source` | `semantic`, `lexical`, etc. |

Empty hits with `ok` — query may not match indexed scope (fast mode, wrong repo, stale index).

---

## Symptom → command FAQ

Organized by what you **see** or **hear** — each entry explains **why** it happens and **exactly** which command fixes it.

### Install & setup

| Symptom | Why | Fix |
|---------|-----|-----|
| `scubiee: command not found` | Layer 1 missing — package not installed | `uv tool install scubiee` |
| `machine_not_setup` on init | Layer 2 missing — no accel profile | `scubiee setup` |
| `[scubiee] Try: scubiee setup --repair` (faiss) | Vector lib missing in uv env | `scubiee setup --repair` |
| Doctor shows `multiple_installs: true` | conda + uv both on PATH | Remove duplicate; keep uv tool only |
| Doctor `binaries_match: false` | Wrong scubiee.exe invoked | Call `expected_binary` from doctor JSON |
| Setup hangs on Windows | Often iGPU + DML | `scubiee setup --repair --profile cpu` |
| `not_configured` in preflight | Embed stack incomplete | `scubiee setup --repair` |

### Enrollment & init

| Symptom | Why | Fix |
|---------|-----|-----|
| Agent: `managed: false` | Layer 3 or 4 missing | `init .` then `connect --cursor`, reload MCP |
| `status` shows `enrolled: false` | Never initialized this folder | `scubiee init .` |
| Init prompts “25,000+ files” | Safety gate | `--confirm` or `--fast --roots packages,src` |
| Init cancelled at y/n | User declined TTY prompt | Re-run and confirm, or `--confirm` |
| `path_too_broad` | Tried to index `$HOME` or `C:\` | `cd` into project subfolder |
| `inside_ce_home` | Init path inside `~/.scubiee` | Use normal repo path |
| Repeat init re-indexes everything | Expected on `--force`; else use sync | `scubiee sync .` for incremental |

### IDE / MCP / connect

| Symptom | Why | Fix |
|---------|-----|-----|
| Cursor shows Scubiee MCP red | Daemon down or bad MCP JSON | `doctor .`, `engine ensure .`, fix JSON |
| MCP works in one repo, not another | Missing project `.cursor/mcp.json` | `cd that-repo && scubiee connect --cursor` |
| Kiro/Copilot/Cline/Roo broken | Special-4 needs per-repo connect | Connect **inside each project** |
| After upgrade MCP stale | Pin format / env vars old | `scubiee upgrade` then `connect --cursor` |
| Agent told to run `resume` but only one repo paused | Confused global vs per-repo | **`activate .`** for pause; **`resume`** for global stop |
| `warming: true` in MCP status | Cold runtime | Retry locate tool once — don’t poll status every turn |

### Index & search

| Symptom | Why | Fix |
|---------|-----|-----|
| Search misses new files | Index stale | `scubiee sync .` |
| `freshness.clean: false` | Merkle diff non-empty | `scubiee sync .` |
| Only `.py` in `packages/` found | Fast index mode | `scubiee init .` without `--fast`, or widen `--roots` |
| `sync-now` blocked | Repo paused | `scubiee activate .` |
| Search error `daemon` unreachable | Engine down | `scubiee engine ensure .` or `--local` |
| Empty search results | Wrong repo path or scope | Check `status .`, verify cwd |

### Engine & daemon

| Symptom | Why | Fix |
|---------|-----|-----|
| `engine status` → not running | Daemon stopped or never started | `scubiee engine start` or `ensure .` |
| Globally stopped + `engine start` blocked | MCP torn down — need global resume | `scubiee resume` |
| Engine stops randomly | Watchdog restart or RAM pressure | Check `~/.scubiee/watchdog.log`, `resources` |
| Port 8765 in use | Another process bound port | Change `--port` or kill conflicting process |

### Stop / pause / wipe

| Symptom | Why | Fix |
|---------|-----|-----|
| “Run scubiee resume” on every command | Global stop active | `scubiee resume` |
| One repo slow, others fine | Per-repo pause | `scubiee activate .` |
| Want to uninstall one project completely | Need wipe not remove | `scubiee wipe . --confirm` |
| `remove` left index on disk | By design — registry only | `wipe . --confirm` or `remove --delete-store` |
| Wipe exit 2 | No `--confirm` in script | Add `--confirm` or use TTY prompt |
| Wipe `--all` leaves files | Windows file locks | `halt`, quit IDE, `unlock-tool`, wipe again |

### Upgrade & Windows locks

| Symptom | Why | Fix |
|---------|-----|-----|
| `uv tool install` Access denied (os error 5) | Cursor holds python.exe | `scubiee unlock-tool`, retry install |
| Upgrade `quiesce_failed` | Processes/locks | `halt`, `unlock-tool`, `upgrade` |
| Upgrade OK but MCP broken | Rebind skipped or failed | `scubiee connect --all` |
| Version unchanged after upgrade | uv didn’t bump | Check `upgrade` JSON `warning`; `unlock-tool` |
| Search broken after upgrade | Embedding rebuild needed | `upgrade --reindex` or `rebuild` |

### Diagnostics

| Symptom | Why | Fix |
|---------|-----|-----|
| Doctor `manifest.ok: false` | Corrupt publication | `scubiee rebuild .` |
| Doctor `journal.pending: true` | Dirty journal | `scubiee doctor . --fix` |
| Diagnose `stale_accel: true` | accel.json vs packages mismatch | `scubiee setup --repair` |
| Certify fails in CI | No daemon | `certify --skip-daemon` |

---

## Platform-specific behavior

Scubiee is cross-platform but **paths, locks, and GPU profiles differ**. Same commands; different failure modes.

---

### Windows

#### Install location

```text
Package:  %APPDATA%\uv\tools\scubiee\
Python:   %APPDATA%\uv\tools\scubiee\Scripts\python.exe
CLI:      %APPDATA%\uv\tools\scubiee\Scripts\scubiee.exe
Data:     %USERPROFILE%\.scubiee\
```

#### Commands especially important on Windows

| Command | When |
|---------|------|
| `scubiee unlock-tool` | **Access denied** on uv install/upgrade — Cursor locks tool dir |
| `scubiee halt` | Before wipe/upgrade while Cursor stays open |
| `scubiee setup --profile dml` | AMD/NVIDIA discrete GPU (DirectML) |
| `scubiee setup --profile cpu` | Intel iGPU-only laptops (DML hangs) |

#### Windows-specific quirks

- **File locks:** Cursor/Claude spawn `python.exe` from uv tools dir — blocks package swap. Admin **does not** help; use `unlock-tool` or quit IDE.
- **Terminal UX (0.3.13+):** colorama + UTF-8 for progress bars in cmd/PowerShell.
- **Symlinks:** HF model cache may warn about symlinks — setup sets `HF_HUB_DISABLE_SYMLINKS_WARNING`.
- **Wipe audit:** `wipe --all` JSON `audit.remaining` often lists MCP paths still locked — re-run after `halt` + quit Cursor.
- **Path separators:** CLI accepts both `\` and `/` in paths; JSON may escape backslashes.

#### Typical Windows recovery sequence

```powershell
scubiee halt
scubiee unlock-tool
uv tool install --force scubiee --index-url https://pypi.org/simple
scubiee setup --repair
scubiee upgrade
scubiee connect --cursor
scubiee resume
scubiee doctor .
```

---

### macOS

#### Install location

```text
Package:  ~/.local/share/uv/tools/scubiee/   (uv default)
Data:     ~/.scubiee/
```

#### Profile selection

| Hardware | Typical command |
|----------|-----------------|
| Apple Silicon | `scubiee setup` → auto `mlx` |
| Intel Mac | Often `cpu` or `cuda` if eGPU (rare) |

#### macOS-specific notes

- **Zed MCP:** `~/.config/zed/settings.json` (or `~/Library/Application Support/Zed` on some layouts) — connect writes `context_servers`.
- **VS Code paths:** `~/Library/Application Support/Code/User/` for Copilot/Cline/Roo globalStorage.
- **File locks:** Less aggressive than Windows; upgrade rarely needs `unlock-tool` (command is Windows-focused but harmless if invoked).
- **Gatekeeper:** First MCP spawn may prompt for Python — allow uv tool Python.

---

### Linux

#### Install location

```text
Package:  ~/.local/share/uv/tools/scubiee/
Data:     ~/.scubiee/
```

#### Profile selection

| Hardware | Typical command |
|----------|-----------------|
| NVIDIA + drivers | `scubiee setup` → auto `cuda` |
| CPU only / VM | `scubiee setup --profile cpu` |

#### Linux-specific notes

- **CUDA:** Requires NVIDIA driver + compatible ORT CUDA wheel — `doctor` / `preflight` surface missing CUDA.
- **systemd:** Logon supervisor behavior differs; `engine autostart` registers user-level task where supported.
- **Permissions:** Ensure `~/.scubiee` writable; root-owned home breaks init.
- **Headless servers:** No IDE — use CLI `search`, `status`; skip `connect` unless batch-editing MCP for remote dev containers.

---

### Cross-platform comparison

| Topic | Windows | macOS | Linux |
|-------|---------|-------|-------|
| Recommended install | `uv tool install scubiee` | Same | Same |
| GPU path | DML / CPU | MLX / CPU | CUDA / CPU |
| Unlock tool dir | **`unlock-tool` often required** | Rare | Rare |
| IDE lock issues | Cursor holds uv python | Occasional | Rare |
| Data home | `%USERPROFILE%\.scubiee` | `~/.scubiee` | `~/.scubiee` |
| Engine default URL | `http://127.0.0.1:8765` | Same | Same |
| Full uninstall | `wipe --all --confirm` | Same | Same |

---

## Related documentation

- [How everything works](./how-everything-works.md) — concepts & architecture
- [Commands reference (quick tables)](../docs/web-info/commands-reference.md)
- [Repository lifecycle](../docs/web-info/repo-lifecycle.md)
- [Error codes & exit codes](./error-codes-reference.md)
- [Data & files reference](./data-and-files-reference.md)
- [Complete fix guide](./complete-fix-guide.md)
- [MCP tools reference](../docs/web-info/mcp-tools-reference.md)
