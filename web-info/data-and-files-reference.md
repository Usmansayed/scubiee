# Data & files reference

Every important path, file, and directory Scubiee uses — what it contains, when it appears, and what happens if you delete it.

**Version:** 0.3.14 · **Concepts:** [how-everything-works.md](./how-everything-works.md)

---

## Overview map

```text
Machine-wide                          Per-repository
─────────────                         ──────────────
~/.scubiee/                           <repo>/.scubiee/
  registry.json                         id.json
  accel.json                            (optional id dir)
  prefs.json
  projects/<ce_id>/          ←─────── bound by id.json
  upgrade_history.json
  engine.log
  watchdog.log
  vectordb/                   (collections keyed by repo)

IDE / tool configs (from connect)
  ~/.cursor/mcp.json
  ~/.cursor/rules/scubiee.mdc
  <repo>/.cursor/mcp.json
  <repo>/.kiro/settings/mcp.json
  … (see connect tool table)

Install location
  Windows: %APPDATA%\uv\tools\scubiee\
  Unix:    ~/.local/share/uv/tools/scubiee/  (uv layout)
```

---

## `~/.scubiee/` (CTX_HOME)

Override with env **`CTX_HOME`** (advanced/testing only).

| Path | Purpose | Safe to delete? |
|------|---------|-----------------|
| `registry.json` | All enrolled repos, paths, pause state, project metadata | Wipe recreates empty; loses enrollment |
| `accel.json` | GPU/CPU profile, batch size, calibration | `setup --repair` recreates |
| `prefs.json` | User settings (`automatic` vs `mcp_cli` registration mode) | Recreated with defaults |
| `projects/<project_id>/` | **Index store** — chunks, graph, FAISS, merkle, meta | `wipe` or `remove --delete-store` |
| `upgrade_history.json` | Component versions applied during upgrades | Upgrade may re-run steps |
| `engine.log` | Daemon log | Yes (diagnostic only) |
| `watchdog.log` | Watchdog restarts | Yes |
| `vectordb/` | VectorDB collection metadata/storage | Repo wipe drops collections |
| `indexes/` | **Legacy** per-repo index paths (older versions) | Wipe cleans |

---

## `<repo>/.scubiee/`

| Path | Purpose |
|------|---------|
| `id.json` | Stable `project_id` (`ce_…`) for this checkout |
| (other files) | Rare; mostly id binding |

**If deleted but registry still has path:** Scubiee may recover id from registry on next init.  
**If both gone:** New project id → **full re-index**.

Often listed in `.gitignore` — do not commit secrets; id is not secret but is machine-local binding.

---

## Index store (`~/.scubiee/projects/<project_id>/`)

Typical contents (names may vary by version):

| Artifact | Role |
|----------|------|
| `meta.json` | Schema version, embed model, dim, timestamps |
| Merkle / manifest | Change detection for sync |
| Chunk store | Parsed code segments |
| Graph | Import/call structure |
| FAISS / vector blobs | Embedding index |
| Lexical index | Text search complement |

**Size:** scales with indexed source volume (not full repo if skips apply).

**Delete effect:** Semantic search empty until `init`/`rebuild` repopulates.

---

## Registry (`registry.json`)

Conceptual structure per project:

```json
{
  "projects": {
    "ce_abc123…": {
      "paths": ["C:\\dev\\my-repo"],
      "managed": true,
      "state": "active",
      "pause_reason": null
    }
  }
}
```

| Field | Meaning |
|-------|---------|
| `paths` | Checkout paths bound to this id |
| `managed` | Enrolled (vs detached) |
| `state` | `active`, `paused`, etc. |
| `pause_reason` | Why pause was set |
| `forget_pending` | Dashboard forget in progress |

Edit manually only if you know registry semantics — prefer CLI `wipe`/`remove`.

---

## Install locations

### uv tool (recommended Windows/macOS/Linux)

| OS | Typical root |
|----|--------------|
| Windows | `%APPDATA%\uv\tools\scubiee\` |
| Unix | `~/.local/share/uv/tools/scubiee/` or uv cache layout |

Contains:

- `Scripts/scubiee.exe` (Windows) or `bin/scubiee`
- `Scripts/python.exe` — Python used by MCP
- `Lib/site-packages/pipeline/` — package code

**This is what MCP spawn uses** — must match `scubiee --version` python.

### pip / venv

Separate copy under your venv's `site-packages`. Doctor warns if PATH picks wrong binary.

---

## MCP and rule files (from `connect`)

| Tool | User-global | Project-local |
|------|-------------|---------------|
| Cursor | `~/.cursor/mcp.json`, `~/.cursor/rules/scubiee.mdc` | `<repo>/.cursor/mcp.json` |
| Kiro | user steering/MCP | `<repo>/.kiro/settings/mcp.json` |
| Copilot | — | `<repo>/.vscode/mcp.json`, `<repo>/.mcp.json` |
| Cline | — | `<repo>/.cline/mcp.json` |
| Roo | — | `<repo>/.roo/mcp.json` |

**Wipe single repo:** removes project-local entries via `strip_all_project_tool_surfaces`.  
**Wipe --all:** removes user-global MCP entries too.

MCP server block typically includes:

- command: path to `scubiee-mcp` or `python -m pipeline.mcp_server`
- env: `CTX_REPO` (absolute on project pin), optional `CTX_MCP_SURFACE`

---

## Logs and diagnostics

| Output | Command | Use |
|--------|---------|-----|
| `Desktop/scubiee-diagnose.json` | `scubiee diagnose --desktop` | Support bundle |
| stdout JSON | `scubiee doctor .` | Quick readiness |
| `engine.log` | automatic | Daemon crashes, embed errors |
| `watchdog.log` | automatic | Restart loops |

---

## Environment variables (operator-relevant)

| Variable | Effect |
|----------|--------|
| `CTX_HOME` | Override `~/.scubiee` |
| `CTX_ENGINE_URL` | Daemon URL (default `http://127.0.0.1:8765`) |
| `CTX_REPO` | Repo root for MCP (set in mcp.json) |
| `CTX_PROJECT_ID` | Bind MCP to specific id |
| `CTX_MCP_SURFACE` | Tool set: `phase` (default), `nav`, `grep`, … |
| `CTX_MCP_LEAN_ECHO` | Opt-in trim echoed MCP fields |
| `CTX_ALLOW_TEST_HOME` | Allow temp CTX_HOME in tests |
| `CTX_RM_DISABLE` | Disable RAM admission pauses |
| `CTX_WATCHDOG` | `0` disables watchdog |
| `CTX_INCREMENTAL_MAX_TOUCH` | File count before confirm (default 400) |
| `CTX_FAST_ROOTS` | Comma roots for `--fast` |
| `NO_COLOR` | Disable CLI colors |

---

## What delete/wipe removes

| Action | registry | projects/ | .scubiee in repo | vectordb | source code | global MCP |
|--------|----------|-----------|------------------|----------|-------------|------------|
| `pause` | keep | keep | keep | keep | keep | keep |
| `remove` | update | optional | keep | keep | keep | keep |
| `wipe` (repo) | remove path | delete if last path | remove | drop | **keep** | keep global |
| `wipe --all` | clear | all | all repos | all | **keep** | remove |

---

## Related

- [how-everything-works.md](./how-everything-works.md)
- [complete-fix-guide.md](./complete-fix-guide.md)
- [../docs/web-info/repo-lifecycle.md](../docs/web-info/repo-lifecycle.md)
