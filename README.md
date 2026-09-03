<p align="center">
  <img src="visuals/banner.png" alt="Scubiee" width="420">
</p>

<p align="center">
  <a href="https://pypi.org/project/scubiee/"><img src="https://img.shields.io/pypi/v/scubiee?style=flat&color=C4783A" alt="PyPI"></a>
  <a href="https://pypi.org/project/scubiee/"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat" alt="Python 3.10+"></a>
  <a href="https://pypi.org/project/scubiee/"><img src="https://img.shields.io/pypi/dm/scubiee?style=flat&color=blue" alt="Downloads"></a>
  <a href="https://github.com/Usmansayed/new-context-engine"><img src="https://img.shields.io/github/stars/Usmansayed/new-context-engine?style=flat" alt="GitHub stars"></a>
  <br>
  <img src="https://img.shields.io/badge/OS-Windows-0078D6?style=flat&logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/OS-macOS-000000?style=flat&logo=apple&logoColor=white" alt="macOS">
  <img src="https://img.shields.io/badge/OS-Linux-FCC624?style=flat&logo=linux&logoColor=black" alt="Linux">
  <img src="https://img.shields.io/badge/MCP-compatible-8A2BE2?style=flat" alt="MCP">
  <img src="https://img.shields.io/badge/privacy-local%20first-2ea44f?style=flat" alt="Local first">
</p>

<p align="center">
  <b>Local context engine for AI coding tools.</b><br>
  Index your repository on your machine. Agents search by meaning — <code>map</code> · <code>focus</code> · <code>grep</code> — instead of grepping blindly through files.
</p>

---

Type `scubiee connect` once and your AI coding assistant gets a **local index** of the repo — ranked discovery, deep focus, and exact search — without uploading code to a vendor.

- **Fully local.** Tree-sitter + embeddings on disk. Code never leaves the machine. The only network step is a one-time model download at setup (~270 MB).
- **Built for agents.** MCP tools `map` · `focus` · `grep` in Cursor, Claude Code, Copilot, Kiro, and more.
- **Not a cloud RAG.** A real local engine with live Merkle sync. Index once, stay fresh as you edit and pull.

<p align="center">
  <img src="visuals/image.png" alt="Scubiee map, focus, and grep" width="900">
</p>
<p align="center">
  <em>Ranked map hits, focused spans, exact grep — all against a local index.</em>
</p>

---

## Install

Requires **Python 3.10+**. Recommended installer: [uv](https://docs.astral.sh/uv/).

```bash
uv tool install scubiee
```

<details>
<summary>Or with pip</summary>

```bash
pip install -U scubiee
```

</details>

---

## Setup (once per machine)

Downloads the embedding model and picks CUDA / DirectML / MLX / CPU for your hardware.

```bash
scubiee setup
```

---

## Index a repo

Parses and embeds the project into `~/.scubiee`. Run this inside the repository you want agents to understand.

```bash
cd /path/to/your/repo
scubiee init .
```

---

## Connect your IDE

Wires MCP + agent rules so the assistant can call Scubiee. Then **reload MCP** in the IDE (Cursor: Settings → MCP → refresh).

```bash
scubiee connect --cursor
```

Other tools: `--claude-code`, `--copilot`, `--kiro`, `--all`, and more — see [getting started](docs/web-info/getting-started.md).

`init` indexes. `connect` attaches the assistant. You need both.

---

## What agents get

| Tool | Role |
|------|------|
| **`map`** | Ranked files & symbols — overview without dumping bodies |
| **`focus`** | Deep context for one target (span, outline, neighbors) |
| **`grep`** | Exact search inside the index |
| **`gate` / `status`** | Tiny managed check at session start |

Also: `glob`, `workspace`, `expand` — [MCP tools reference](docs/web-info/mcp-tools-reference.md).

---

## How it works

```text
  setup (once)  →  init (per repo)  →  connect (per IDE)
       │                 │                    │
       ▼                 ▼                    ▼
  download model    parse + embed         MCP + rules
                    ~/.scubiee            reload IDE
```

```text
  AI coding tool  ──MCP──►  Scubiee (localhost)  ──►  ~/.scubiee
```

A small local daemon serves search. Background sync keeps enrolled repos fresh. Indexing and retrieval stay on your machine.

---

## Day-to-day

After a big pull or refactor, refresh the index:

```bash
scubiee sync .
```

Check enrollment and health:

```bash
scubiee status .
scubiee doctor .
```

Search from the terminal (no IDE required):

```bash
scubiee search "auth middleware" .
```

Upgrade the package and rebind MCP:

```bash
scubiee upgrade
```

Lifecycle (pause / stop / wipe) is covered in [repo lifecycle](docs/web-info/repo-lifecycle.md). Full flag list: [complete CLI reference](web-info/complete-cli-reference.md).

---

## Privacy

- **Code** stays on disk — parsed and embedded locally; nothing leaves for search.
- **Model** downloads once during `setup` (~270 MB). After that, indexing is offline.
- Data lives under `~/.scubiee` and `<repo>/.scubiee`.

---

## Docs

| | |
|--|--|
| Getting started | [docs/web-info/getting-started.md](docs/web-info/getting-started.md) |
| Install & debug | [docs/web-info/install-and-debug.md](docs/web-info/install-and-debug.md) |
| MCP tools | [docs/web-info/mcp-tools-reference.md](docs/web-info/mcp-tools-reference.md) |
| Troubleshooting | [docs/web-info/troubleshooting.md](docs/web-info/troubleshooting.md) |
| How everything works | [web-info/how-everything-works.md](web-info/how-everything-works.md) |

---

## FAQ

**Does `init` connect Cursor?**  
No. `init` indexes. `connect` writes MCP and rules. Then reload MCP.

**Does my code get uploaded?**  
No. Only the embedding model downloads during setup.

**Agent says `managed: false`?**  
Run `init` and `connect` in that project, then reload MCP. For Kiro / Copilot / Cline / Roo, run `connect` inside each repo.

**Windows "Access denied" on upgrade?**  
`scubiee unlock-tool`, then retry. Quitting the IDE helps.

**Need a support bundle?**  
`scubiee diagnose --no-tests --desktop` — attach the Desktop JSON and a tail of `~/.scubiee/engine.log`.

---

**PyPI:** [scubiee](https://pypi.org/project/scubiee/) · **Release:** 0.3.14 · Contributors: `uv pip install -e .` then `scubiee setup`
