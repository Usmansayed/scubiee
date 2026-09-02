# Scubiee — Product guide for website & marketing docs

> **Version:** [0.3.14](https://pypi.org/project/scubiee/0.3.14/) (published on PyPI)  
> **Audience:** website copywriters, product marketers, technical writers, and anyone drafting public-facing Scubiee pages.  
> **Operator docs (end users):** [`../docs/web-info/README.md`](../docs/web-info/README.md)  
> **Short marketing snippets:** [`website-content.md`](./website-content.md)  
> **Engineering depth:** [`context-engine-internals.md`](./context-engine-internals.md)

This document explains **what Scubiee is**, **who it is for**, **how it works**, and **what to say on each website page** — in enough detail to write accurate product copy without reading the codebase.

---

## Table of contents

1. [Executive summary](#executive-summary)
2. [The problem Scubiee solves](#the-problem-scubiee-solves)
3. [The solution in one paragraph](#the-solution-in-one-paragraph)
4. [Who Scubiee is for](#who-scubiee-is-for)
5. [Core product concepts](#core-product-concepts)
6. [How Scubiee works (user journey)](#how-scubiee-works-user-journey)
7. [Architecture (website-friendly)](#architecture-website-friendly)
8. [Features in depth](#features-in-depth)
9. [MCP tools — what the AI actually uses](#mcp-tools--what-the-ai-actually-uses)
10. [Supported AI coding tools](#supported-ai-coding-tools)
11. [Platforms & hardware acceleration](#platforms--hardware-acceleration)
12. [Privacy, security, and data locality](#privacy-security-and-data-locality)
13. [Repository lifecycle (manage, pause, unmanage)](#repository-lifecycle-manage-pause-unmanage)
14. [Installation & first-run copy](#installation--first-run-copy)
15. [Comparison angles (vs alternatives)](#comparison-angles-vs-alternatives)
16. [Suggested website page structure](#suggested-website-page-structure)
17. [FAQ for public website](#faq-for-public-website)
18. [Social proof & use-case stories](#social-proof--use-case-stories)
19. [Terminology & brand rules](#terminology--brand-rules)
20. [SEO & messaging keywords](#seo--messaging-keywords)

---

## Executive summary

**Scubiee** is a **local code context engine** for AI-assisted software development. It indexes your repositories on your machine, builds semantic and structural search indexes, and exposes them to AI coding tools through the **Model Context Protocol (MCP)** and a command-line interface.

Your code **never leaves your machine** for search and retrieval. The only network use during normal operation is a **one-time model download** during setup (~270 MB embedding model).

**Product identity (always use consistently):**

| Item | Value |
|------|--------|
| Product name | **Scubiee** |
| PyPI / CLI package | `scubiee` |
| MCP server key in `mcp.json` | **`scubiee`** |
| User data directory | **`~/.scubiee`** |
| Per-repo marker | **`<repo>/.scubiee/id.json`** |
| Legacy names | Do **not** use `context-engine` in user-facing copy |

**One-line pitch:**  
Scubiee turns your repository into continuously maintained, AI-ready context — semantic search, graph-aware retrieval, and live re-indexing — entirely on your hardware.

**Elevator pitch (3 sentences):**  
AI coding assistants are good at editing files you point them to, but bad at finding the *right* files in a large codebase. Scubiee indexes your repo locally, keeps it fresh as you code, and gives Cursor, Claude Code, Copilot, and other tools MCP-powered **map**, **focus**, and **grep** capabilities so agents search by meaning—not random grepping. Setup takes minutes; everything stays offline after the initial model download.

---

## The problem Scubiee solves

### What goes wrong without Scubiee

1. **Discovery noise** — Agents grep broadly, read wrong files, or hallucinate paths.
2. **Stale context** — Files changed since the chat started; the agent doesn't know.
3. **No shared index** — Every session re-explores the repo from scratch.
4. **Cloud search tradeoffs** — Uploading code to a vendor index raises privacy and compliance concerns.
5. **DIY RAG complexity** — Building embeddings, chunking, incremental sync, and MCP wiring takes weeks.

### What users feel

- “The AI keeps opening the wrong module.”
- “It can't find where authentication is handled.”
- “We can't send our repo to a cloud indexer.”
- “Cursor's built-in search isn't enough for our monorepo.”

Scubiee addresses discovery and freshness **locally**, as a layer **under** the AI tool—not a replacement for the IDE.

---

## The solution in one paragraph

Scubiee runs a **local daemon** on your machine that maintains an **index** of each enrolled repository: parsed code structure, text chunks, embedding vectors, and graph relationships (imports, calls). A thin **MCP server** connects your AI tool to that daemon. When the agent asks “where is billing handled?”, Scubiee returns **ranked locations** (`map`) and **focused code spans** (`focus`) from the index—not from guessing filenames. When you edit or pull changes, **incremental sync** updates the index in the background. One **`scubiee connect`** command wires MCP configs and agent rules for Cursor, Copilot, Kiro, and other supported tools.

---

## Who Scubiee is for

### Primary audiences

| Audience | Why Scubiee |
|----------|-------------|
| **Individual developers** using Cursor, Copilot, Claude Code, etc. | Better agent accuracy on personal and work repos without cloud upload |
| **Teams with private / air-gapped code** | Local-only indexing; no code transmission for search |
| **Monorepo maintainers** | Semantic + structural search across large trees |
| **Power users** | CLI search, dashboard, lifecycle control, honest wipe/audit |

### Not the primary audience (be honest on website)

- Teams wanting **hosted** multi-user code search in the cloud (Scubiee is local-first).
- Users who only edit one file and never need cross-repo discovery.
- Environments where installing Python 3.10+ and ~300 MB model cache is impossible.

---

## Core product concepts

Explain these clearly on the **How it works** and **Docs** pages.

### 1. Machine setup (`scubiee setup`)

**Once per machine.** Detects GPU/CPU/MLX, installs the right ONNX Runtime stack, downloads the **CodeRankEmbed** model, calibrates batch size, writes `~/.scubiee/accel.json`.

- **`scubiee setup --repair`** — safe to re-run after upgrades or broken installs.
- Does **not** index any repository by itself.

**Website copy:** “One-time machine setup detects your hardware and downloads the embedding model locally.”

---

### 2. Repository enrollment & indexing (`scubiee init`)

**Per repository.** Registers the repo in `~/.scubiee/registry.json`, writes `<repo>/.scubiee/id.json` (stable project id), parses and embeds code, starts or attaches to the daemon.

- **`scubiee init . --fast`** — index `.py` under standard code roots (`packages`, `src`, …).
- **`scubiee init . --confirm`** — required when >400 indexable files would be touched (safety gate).
- Does **not** configure Cursor or other IDEs.

**Website copy:** “Point Scubiee at a repo; it builds a searchable index on your disk.”

---

### 3. Tool connection (`scubiee connect`)

**Per machine and/or per project.** Writes MCP server entries and **agent rules** (e.g. `.cursor/rules/scubiee.mdc`) so the AI knows to call Scubiee for discovery.

- **Cursor / Claude Code** — typically user-global MCP + project pin.
- **Kiro, Copilot, Cline, Roo Code** — also need **`connect` run inside each project** (workspace-local MCP files).

**Critical message for website:** **`init` ≠ `connect`.** Index first, connect second, reload MCP third.

---

### 4. The daemon (engine)

A local HTTP service (default `http://127.0.0.1:8765`) that:

- Serves search, grep, and index operations to MCP and CLI.
- Runs **background sync** for enrolled repos.
- Respects **resource limits** (RAM admission, embed batching).
- Is restarted by a lightweight **watchdog** if it crashes.

**Website copy:** “A small local service keeps your index warm and answers search requests in milliseconds.”

---

### 5. MCP (Model Context Protocol)

Standard protocol for AI tools to call external capabilities. Scubiee registers as server name **`scubiee`** with tools like `map`, `focus`, `grep`. The agent calls these instead of (or before) naive file grepping.

---

### 6. Managed vs unmanaged

| State | Meaning |
|-------|---------|
| **Unmanaged** | Folder never initialized — Scubiee tools should not be used for discovery here |
| **Managed / active** | Enrolled and indexed — agent may use MCP tools |
| **Paused** | Still enrolled; background sync/index blocked until **`scubiee activate`** |
| **Wiped** | All Scubiee data for that repo removed; back to unmanaged |

Agents call **`gate()`** or **`status()`** once at session start to learn if the workspace is managed.

---

## How Scubiee works (user journey)

Use this as the **Getting started** page narrative.

```text
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1 — INSTALL (once)                                        │
│  uv tool install scubiee==0.3.14                                │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2 — SETUP (once per machine)                              │
│  scubiee setup --repair                                         │
│  • Detect GPU: CUDA / DirectML / MLX / CPU                      │
│  • Download CodeRankEmbed model (~270 MB)                       │
│  • Write accel profile                                          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3 — INIT (per repository)                                 │
│  cd your-repo && scubiee init .                                 │
│  • Assign project id (ce_…)                                     │
│  • Parse, chunk, embed, graph                                   │
│  • Store under ~/.scubiee/projects/<id>/                        │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4 — CONNECT (per tool / per project)                      │
│  scubiee connect --cursor                                       │
│  • Write MCP config + agent rules                               │
│  • Reload MCP in IDE                                            │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 5 — DAILY USE                                             │
│  Agent: gate() → map("auth middleware") → focus(target)         │
│  You:  scubiee sync . after git pull                            │
└─────────────────────────────────────────────────────────────────┘
```

**Time expectations (honest marketing):**

| Step | Typical duration |
|------|------------------|
| Install | 1–3 minutes |
| Setup (incl. model download) | 3–10 minutes first time |
| Init small repo (~100 files) | 1–5 minutes |
| Init large monorepo | Minutes to tens of minutes; may require `--confirm` |
| Connect | Seconds |

---

## Architecture (website-friendly)

```text
┌──────────────────────┐
│  Your AI IDE         │  Cursor, Copilot, Kiro, Claude Code, …
│  (MCP client)        │
└──────────┬───────────┘
           │  MCP stdio  (tools: map, focus, grep, …)
           ▼
┌──────────────────────┐
│  scubiee-mcp         │  Thin adapter; session + repo binding
└──────────┬───────────┘
           │  HTTP localhost
           ▼
┌──────────────────────┐
│  Scubiee Engine      │  Daemon + watchdog
│  (port 8765)         │  IndexManager · ResourceManager · RuntimeManager
└──────────┬───────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─────────┐ ┌──────────────┐
│ Vectors │ │ Graph/chunks │   FAISS + TurboQuant · AST graph · Merkle sync
│ + embed │ │ + manifest   │
└─────────┘ └──────────────┘
     All stored under ~/.scubiee/ and <repo>/.scubiee/
```

**Indexing pipeline (technical but website-safe):**

1. **Scan** — discover files; Merkle tree for change detection  
2. **Parse** — Tree-sitter AST across many languages  
3. **Graphify** — imports, calls, structure  
4. **Chunk & compress** — symbol-oriented chunks (default `mix` compression)  
5. **Embed** — CodeRankEmbed FP16 (GPU path depends on platform)  
6. **Index** — FAISS vectors + lexical index + graph edges  
7. **Serve** — hybrid retrieval fuses semantic + lexical + graph signals  

**Do not oversell on website:** Scubiee is not a general-purpose database, CI system, or cloud IDE. It is a **local retrieval layer for code**.

---

## Features in depth

Use these as **feature cards** or expandable sections.

### Semantic code search

- Search by **meaning**, not exact text: “session validation middleware” finds relevant handlers even without those exact words.
- Powered by **CodeRankEmbed** + **FAISS** vector index.
- CLI: `scubiee search "query" .`
- MCP: `map(query)` for overview, `focus(target)` for code bodies.

### Graph-aware retrieval

- Understands **imports, callers, callees**, and file structure—not isolated text blobs.
- `focus(mode=neighbors)` and `focus(mode=call_sites)` expose relationships.
- Helps agents follow real code flow instead of random adjacent files.

### Live incremental indexing

- **Merkle sync** detects changed files efficiently.
- `scubiee sync .` or background daemon refresh after edits.
- Reduces “the AI is reading stale code” failures.

### Hybrid retrieval

- Combines **dense vectors**, **lexical** match, and **graph** signals.
- Exact literals still available via MCP `grep` and CLI search modes.

### Multi-tool MCP connectivity

- One product wires **many AI tools** via `scubiee connect --<tool>`.
- Clean removal via `scubiee disconnect`.
- Agent **rules** teach when to use Scubiee vs native tools.

### GPU-aware acceleration (automatic)

- Picks best backend per machine; user rarely chooses manually.
- **Windows discrete GPU** → DirectML  
- **Windows CPU-only / iGPU** → CPU (avoids DML hang on Intel UHD laptops)  
- **Apple Silicon** → MLX Metal  
- **Linux NVIDIA** → CUDA  

### Multi-repository support

- `scubiee init` per repo; registry tracks many projects.
- **Project id** (`ce_…`) stable across moves when identity file travels with repo.
- Dashboard lists repos; pause/activate per repo.

### Operator dashboard

- `scubiee dashboard` — local web UI for repo list, pause/activate, hardware status.
- Complements CLI; not required for daily use.

### Diagnostics & self-healing

- **`scubiee doctor`** — readiness + install identity (duplicate PATH binaries on Windows).
- **`scubiee diagnose --desktop`** — shareable JSON for support.
- **`scubiee setup --repair`** — fix broken ORT/FastEmbed after bad upgrade.
- **`scubiee unlock-tool`** — Windows file-lock recovery before reinstall.

### Safe lifecycle & wipe

- **Repo wipe** requires confirmation (`scubiee wipe . --confirm`).
- Removes enrollment, index, VectorDB, `.scubiee`, repo MCP/rules — **not your source code**.
- **Full machine wipe** with audit of leftover paths (`wipe --all --confirm`).

### Global stop / resume

- **`scubiee stop`** — machine-wide pause of engine + MCP surfaces (e.g. before upgrade).
- **`scubiee resume`** — bring Scubiee back. (There is no `wake` command.)

### One-command upgrade

- **`scubiee upgrade`** — stop processes, swap package, migrate data, restart.
- Critical on Windows where file locks cause `Access denied` during naive pip upgrade.

---

## MCP tools — what the AI actually uses

Default **`phase`** surface (Cursor and most installs). Full reference: [`../docs/web-info/mcp-tools-reference.md`](../docs/web-info/mcp-tools-reference.md).

| Tool | User-visible benefit | Example agent question |
|------|---------------------|------------------------|
| **`gate`** | Tiny “is this repo ready?” check | (automatic at chat start) |
| **`status`** | Full health: managed, warming, paused | “Can I use Scubiee in this workspace?” |
| **`map`** | Ranked map of where to look | “Where is OAuth handled?” |
| **`focus`** | Actual code outline/span/neighbors | “Show the login handler and its callers” |
| **`grep`** | Exact string/regex in indexed files | “Find every `API_KEY` reference” |
| **`glob`** | Files by path pattern | “List all `*test*.py` under packages/” |
| **`workspace`** | Session memory — pins, heatmap | “What did we already look at?” |
| **`expand`** | Re-open a previous code span | (follow-up without re-searching) |
| **`register_project`** | Enroll repo from chat with consent | “Index this folder for me” |

**Recommended agent flow (for docs page):**

`gate()` → `map(query)` → `focus(target)` → edit → `scubiee sync` if needed

**Anti-patterns to document:**

- Polling `status()` every turn when `warming: true` — retry the locate tool once instead.
- Using Scubiee when `managed: false` — run `init` + `connect` first.
- Grepping the whole repo before trying semantic `map`.

---

## Supported AI coding tools

Connect with `scubiee connect --<slug>`.

| Tool | CLI flag | Notes |
|------|----------|-------|
| **Cursor** | `--cursor` | Global MCP + project `.cursor/mcp.json` pin |
| **Claude Code** | `--claude-code` | User-global MCP |
| **Codex** | `--codex` | |
| **Kiro** | `--kiro` | Run connect **inside each repo** |
| **GitHub Copilot / VS Code** | `--copilot` | Workspace `.vscode/mcp.json` |
| **Cline** | `--cline` | Workspace-local MCP |
| **Roo Code** | `--roo-code` | Workspace-local MCP |
| **Continue** | `--continue` | |
| **Zed** | `--zed` | |
| **OpenCode** | `--opencode` | |
| **Amp** | `--amp` | |
| **Pi** | `--pi` | |
| **Devin Desktop** | `--devin-desktop` | |
| **Windsurf** | `--windsurf` | |

**“Special-4” (website callout):** Kiro, Copilot, Cline, and Roo Code need **`scubiee connect` run from inside each project** so workspace-local MCP files get an absolute repo path.

**Connect all:** `scubiee connect --all`  
**Preview:** `scubiee connect --all --dry-run`  
**Disconnect:** `scubiee disconnect --cursor` (etc.)

---

## Platforms & hardware acceleration

| OS | Hardware | Profile | Status |
|----|----------|---------|--------|
| Windows | AMD/NVIDIA discrete | DirectML (`dml`) | Production |
| Windows | Intel iGPU / APU / no dGPU | CPU (`cpu`) | Production — avoids DML hang |
| macOS | Apple Silicon | MLX Metal (`mlx`) | Production |
| macOS | Intel | CoreML / CPU | Supported |
| Linux | NVIDIA | CUDA (`cuda`) | Production |
| Linux | No GPU | CPU | Supported |

**Requirements:**

- Python **3.10+**
- ~**500 MB–1 GB** disk for tool + model + index (varies by repo size)
- Network **only for initial** PyPI install and model download

**Windows note for website:** If `uv tool install` fails with **Access denied**, run **`scubiee unlock-tool`** — not Administrator mode or reboot.

---

## Privacy, security, and data locality

**Messages safe for privacy/compliance pages:**

1. **Code stays local** — Indexing, embedding, and search run on your machine.
2. **No Scubiee cloud** — There is no Scubiee-hosted repository upload service.
3. **Model download only** — HuggingFace/FastEmbed model fetch during setup; after that, offline search works.
4. **You control deletion** — `scubiee wipe` removes local indexes and metadata; `--all --confirm` audits leftovers.
5. **Open install** — Package on PyPI; inspectable CLI and local data under `~/.scubiee`.

**Nuances (honest footnotes):**

- Your **AI tool** (Cursor, etc.) may still send code to **its own** model provider—that is separate from Scubiee.
- Scubiee writes **MCP config and rule files** into IDE config directories; those files contain paths, not your source code.
- **`scubiee diagnose`** output may include paths and versions for support — review before sharing.

---

## Repository lifecycle (manage, pause, unmanage)

Full guide: [`../docs/web-info/repo-lifecycle.md`](../docs/web-info/repo-lifecycle.md).

| User intent | Command | Deletes index? | Deletes source code? |
|-------------|---------|----------------|----------------------|
| Pause background work | `scubiee pause .` | No | No |
| Resume paused repo | `scubiee activate .` | No | No |
| Stop everything (upgrade prep) | `scubiee stop` / `scubiee resume` | No | No |
| **Unmanage + delete Scubiee data** | **`scubiee wipe . --confirm`** | **Yes** | **No** |
| Registry-only removal | `scubiee remove .` | Optional `--delete-store` | No |
| Delete all machine state | `scubiee wipe --all --confirm` | Yes (all repos) | No |

**Website FAQ must clarify:** Wipe removes **Scubiee's index and config**, not your Git working tree.

---

## Installation & first-run copy

**Hero install block (website code panel):**

```bash
# Install (recommended)
uv tool install --force scubiee==0.3.14 --index-url https://pypi.org/simple --refresh

# One-time machine setup
scubiee setup --repair

# Index your repo
cd your-project
scubiee init .

# Connect Cursor (or your tool)
scubiee connect --cursor
# Reload MCP in your IDE
```

**Alternative:** `pip install scubiee` (uv tool install preferred on Windows).

**Upgrade path:** `scubiee upgrade` or reinstall + `setup --repair` + **`connect`** again.

**Support bundle:** `scubiee diagnose --no-tests --desktop` → JSON on Desktop.

---

## Comparison angles (vs alternatives)

### vs native IDE search / agent grep

| | Native grep/read | Scubiee |
|--|------------------|---------|
| Match type | Text | Semantic + graph + text |
| Cross-session memory | None | Workspace session + index |
| Stale after edits | Agent may not know | Incremental sync |
| Setup | Zero | init + connect once |

### vs cloud code intelligence

| | Cloud index | Scubiee |
|--|-------------|---------|
| Code location | Vendor servers | Your disk |
| Air-gapped | No | Yes (after model download) |
| Per-repo control | Vendor-defined | wipe/pause per repo |

### vs build-your-own RAG

| | DIY | Scubiee |
|--|-----|---------|
| Time to value | Weeks | Minutes |
| MCP wiring | Custom | Built-in connect |
| Incremental sync | You build it | Merkle + daemon |
| GPU paths | You integrate ORT/CUDA/MLX | Auto profile |

---

## Suggested website page structure

### Homepage

- **Hero:** One-liner + install command + “local · semantic · MCP”
- **Problem/solution:** 3 bullets (discovery, freshness, privacy)
- **How it works:** 3-step diagram (setup → init → connect)
- **Logo strip:** Cursor, Copilot, Claude, Kiro, …
- **Feature grid:** 6 cards from [Features in depth](#features-in-depth)
- **CTA:** Link to docs + PyPI

### Product / Features page

- Expand each feature with screenshot placeholders (dashboard, MCP tools JSON, search results)
- Architecture diagram
- MCP tools table

### Integrations page

- Full [Supported AI coding tools](#supported-ai-coding-tools) table
- Special-4 callout
- `connect` / `disconnect` examples

### Docs hub (link out)

- Point to [`docs/web-info/`](../docs/web-info/README.md) — not duplicate everything

### Privacy page

- Pull from [Privacy, security, and data locality](#privacy-security-and-data-locality)

### Pricing page

- Scubiee is **free/open install via PyPI** (state license in package if needed — check `pyproject.toml` for website legal).

### Changelog / Releases

- Link PyPI versions + [`whats-changed-since-0.2.88.md`](../docs/whats-changed-since-0.2.88.md)

---

## FAQ for public website

**What is Scubiee?**  
A local code context engine that indexes your repositories and connects to AI coding tools via MCP.

**Does my code get uploaded?**  
No. Indexing and search are local. Only the embedding model downloads from the internet during setup.

**Which AI tools work?**  
Cursor, Claude Code, Copilot, Kiro, Cline, Roo Code, Continue, Zed, OpenCode, and others — see Integrations.

**What's the difference between `init` and `connect`?**  
`init` indexes the repo. `connect` wires your IDE's MCP and agent rules. You need both.

**Does it work on Windows without a GPU?**  
Yes. CPU indexing is supported; setup picks the right profile automatically.

**How do I remove a repo from Scubiee?**  
`scubiee wipe . --confirm` — deletes Scubiee data, not your source files.

**How do I uninstall completely?**  
`scubiee wipe --all --confirm --package` (see uninstall docs for Windows lock steps).

**Why does Cursor say `managed: false`?**  
Run `scubiee init .` and `scubiee connect --cursor` from the project, then reload MCP.

**What's MCP?**  
Model Context Protocol — a standard way for AI assistants to call tools like semantic search.

---

## Social proof & use-case stories

Use as testimonial placeholders or case-study outlines.

1. **Security-conscious team** — “Approved because nothing leaves the laptop; model download was the only outbound call.”
2. **Monorepo developer** — “`map('billing webhook handler')` pointed the agent at the right package first try.”
3. **Windows laptop user** — “CPU profile avoided the DirectML hang on Intel graphics.”
4. **Multi-IDE user** — “Same index served Cursor and Copilot after connect in each workspace.”
5. **Upgrade survivor** — “`unlock-tool` + `setup --repair` fixed Access denied without reinstalling Windows.”

---

## Terminology & brand rules

| Use | Avoid |
|-----|-------|
| Scubiee | Scubie, SCUBIEE as product name in prose |
| `scubiee` (CLI/MCP key) | `context-engine`, `ctx` in user docs |
| `~/.scubiee` | `.context-engine` |
| `init` + `connect` | “Setup does everything” |
| `scubiee resume` | `scubiee wake` |
| `scubiee activate` (per-repo unpause) | `scubiee resume` for per-repo |
| Managed / unmanaged | “Indexed” alone (ambiguous) |

**Version in copy:** Pin **`0.3.14`** in install examples until the next release bump.

---

## SEO & messaging keywords

Primary: scubiee, local code search, semantic code search, MCP server, AI coding assistant, repository indexing, code context engine, cursor mcp, copilot mcp

Secondary: directml code embed, mlx code search, faiss code index, offline code ai, private code rag, merkle sync index, graph code retrieval

Long-tail: “semantic search for cursor”, “local mcp code index”, “scubiee init vs connect”, “wipe scubiee repo”

---

## Related documents

| Document | Purpose |
|----------|---------|
| [`website-content.md`](./website-content.md) | Short snippets, taglines, SEO |
| [`commands-and-setup.md`](./commands-and-setup.md) | Command tables for docs site |
| [`context-engine-internals.md`](./context-engine-internals.md) | Engineering architecture |
| [`../docs/web-info/README.md`](../docs/web-info/README.md) | End-user operator docs |
| [`../docs/web-info/mcp-tools-reference.md`](../docs/web-info/mcp-tools-reference.md) | MCP tool parameters |
| [`../docs/web-info/repo-lifecycle.md`](../docs/web-info/repo-lifecycle.md) | Wipe / pause / unmanage |
