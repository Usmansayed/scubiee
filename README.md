<p align="center">
  <img src="visuals/banner.png" alt="Scubiee" width="420">
</p>

<p align="center">
  <a href="https://pypi.org/project/scubiee/"><img src="https://img.shields.io/pypi/v/scubiee.svg?color=C4783A" alt="PyPI"></a>
  <a href="https://pypi.org/project/scubiee/"><img src="https://img.shields.io/pypi/pyversions/scubiee.svg" alt="Python"></a>
  <a href="https://github.com/Usmansayed/new-context-engine"><img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-111111" alt="Platforms"></a>
</p>

<p align="center">
  <b>Local context engine for AI coding tools.</b><br>
  Index your repository on your machine. Agents search by meaning — <code>map</code> · <code>focus</code> · <code>grep</code> — instead of grepping blindly through files.
</p>

---

Type `scubiee connect` in your terminal and your AI coding assistant gets a **local index** of the repo — ranked discovery, deep focus, and exact search — without uploading code to a vendor.

- **Fully local.** Tree-sitter + embeddings on disk. Code never leaves the machine. The only network step is a one-time model download at setup (~270 MB).
- **Built for agents.** MCP tools `map` · `focus` · `grep` in Cursor, Claude Code, Copilot, Kiro, and more — so assistants query an index instead of dumping whole files into chat.
- **Not a cloud RAG.** A real local engine with live Merkle sync. Index once, stay fresh as you edit and pull.

<p align="center">
  <img src="visuals/image.png" alt="Scubiee map, focus, and grep" width="900">
</p>
<p align="center">
  <em>Scubiee in the loop: ranked map hits, focused spans, exact grep — all against a local index.</em>
</p>

**Get started** (about a minute):

```bash
uv tool install scubiee
scubiee setup                 # once per machine — detect GPU/CPU, download model
cd /path/to/your/repo
scubiee init .                # index this repo
scubiee connect --cursor      # or --claude-code, --copilot, --all, …
```

Then **reload MCP** in your IDE (Cursor: Settings → MCP → refresh).

That's it. `init` indexes. `connect` wires the assistant. You need both.

**Works with** Cursor, Claude Code, GitHub Copilot, Kiro, Cline, Roo, Continue, Zed, OpenCode, and more — [pick your tool](docs/web-info/getting-started.md).

---

## See it in action

<p align="center">
  <img src="visuals/demo.svg" alt="Scubiee demo: init, connect, then map focus grep" width="900">
</p>

Once the index is built, agents query it instead of reading the whole tree:

```text
$ map("auth middleware")
  api/handlers.ts     0.93
  core/engine.rs      0.88
  middleware.ts       0.81

$ focus("validate_token")
  span + neighbors · scoped context, not a full-file dump

$ grep('logger.debug("cache hit")')
  3 hits in the local index
```

From the CLI, the same index is searchable without an IDE:

```bash
scubiee search "auth middleware" .
scubiee status .
scubiee doctor .
```

---

## What it does

| Capability | What you get |
|------------|--------------|
| **`map`** | Ranked files & symbols — overview without dumping bodies |
| **`focus`** | Deep context for one target (span, outline, neighbors) |
| **`grep`** | Exact search inside the **index** |
| **`gate` / `status`** | Tiny managed check at session start |
| **Live sync** | Merkle incremental updates after edits and pulls |
| **Hardware-aware** | CUDA · DirectML · MLX · CPU, chosen at `setup` |
| **Safe lifecycle** | Pause one repo, stop globally, or `wipe` with confirmation |

Also: `glob`, `workspace`, `expand`, and more — [MCP tools reference](docs/web-info/mcp-tools-reference.md).

---

## How it works

```text
  SETUP (once)          INDEX (per repo)         CONNECT (per IDE)
  scubiee setup    →    scubiee init .      →    scubiee connect --cursor
       │                      │                         │
       ▼                      ▼                         ▼
  Detect GPU/CPU         Parse + embed             MCP + agent rules
  Download model         Store under ~/.scubiee    Reload IDE MCP
```

```text
  AI coding tool  ──MCP──►  Scubiee engine (localhost)  ──►  ~/.scubiee
```

A small local daemon serves search. Background sync keeps enrolled repos fresh. Indexing and retrieval stay on your machine.

---

## Prerequisites

| Requirement | Minimum | Check |
|-------------|---------|-------|
| Python | 3.10+ | `python --version` |
| uv (recommended) | any | `uv --version` |
| Disk (first setup) | ~1 GB free | model + indexes |

Install uv: [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) · Windows: `winget install astral-sh.uv`

<details>
<summary>pip / alternative install</summary>

```bash
pip install -U scubiee
scubiee setup
```

On Windows, pin the PyPI index if uv caches go stale:

```bash
uv tool install --force scubiee --index-url https://pypi.org/simple
scubiee setup --repair
```

</details>

---

## Everyday commands

```bash
scubiee status .                 # enrollment + freshness
scubiee sync .                   # incremental re-index after big changes
scubiee search "auth middleware" .
scubiee doctor .                 # readiness + install identity
scubiee upgrade                  # package + migrate + rebind MCP
```

| Goal | Command |
|------|---------|
| Pause one repo | `scubiee pause .` → later `scubiee activate .` |
| Stop machine-wide | `scubiee stop` → later `scubiee resume` |
| Wipe one repo's data | `scubiee wipe . --confirm` |
| Full machine wipe | `scubiee wipe --all --confirm` |

`engine stop` ≠ `scubiee stop`. Global stop tears down MCP until `resume`. Per-repo pause needs `activate`, not `resume`.

---

## Privacy

- **Code** — parsed and embedded locally. Nothing leaves your machine for search or retrieval.
- **Model** — CodeRankEmbed downloads once during `scubiee setup` (~270 MB). After that, indexing is offline.
- **No telemetry** for normal search/index traffic — your repo stays on disk under `~/.scubiee` and `<repo>/.scubiee`.

---

## Documentation

| Guide | Link |
|-------|------|
| Getting started | [docs/web-info/getting-started.md](docs/web-info/getting-started.md) |
| Install & debug | [docs/web-info/install-and-debug.md](docs/web-info/install-and-debug.md) |
| Commands (quick) | [docs/web-info/commands-reference.md](docs/web-info/commands-reference.md) |
| **Every CLI flag** | [web-info/complete-cli-reference.md](web-info/complete-cli-reference.md) |
| MCP tools | [docs/web-info/mcp-tools-reference.md](docs/web-info/mcp-tools-reference.md) |
| Repo lifecycle | [docs/web-info/repo-lifecycle.md](docs/web-info/repo-lifecycle.md) |
| Troubleshooting | [docs/web-info/troubleshooting.md](docs/web-info/troubleshooting.md) |
| How everything works | [web-info/how-everything-works.md](web-info/how-everything-works.md) |

---

## FAQ

**Does `init` connect Cursor?**  
No. `init` indexes. `connect` writes MCP and rules. Then reload MCP.

**Does my code get uploaded?**  
No. Indexing and search are local. Only the embedding model downloads during setup.

**Agent says `managed: false`?**  
Run `scubiee init .` and `scubiee connect --cursor` in that project, then reload MCP. For Kiro / Copilot / Cline / Roo, run `connect` **inside each repo**.

**Windows "Access denied" on upgrade?**  
`scubiee unlock-tool`, then retry. Quitting the IDE helps; admin usually does not.

**Upgrade from 0.2.x?**  
See [What's changed since 0.2.88](docs/whats-changed-since-0.2.88.md), then `scubiee upgrade` and `scubiee setup --repair` if doctor reports missing libs.

---

## Support

```bash
scubiee --version --verbose
scubiee setup --status
scubiee doctor .
scubiee list
scubiee diagnose --no-tests --desktop
```

Attach `Desktop/scubiee-diagnose.json` and a tail of `~/.scubiee/engine.log` when filing issues.

---

## Project

| | |
|--|--|
| **PyPI** | [pypi.org/project/scubiee](https://pypi.org/project/scubiee/) |
| **CLI / MCP** | `scubiee` |
| **Data** | `~/.scubiee` · `<repo>/.scubiee` |
| **Release** | 0.3.14 |

Contributors: `uv pip install -e .` then `scubiee setup`. Maintainers: see `docs/publish-setup.md`.
