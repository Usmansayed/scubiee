# Session Handoff: MacBook CLI + Connect Testing

**Date:** August 30, 2026  
**Repo:** already on your Mac — **pull latest from `origin/main`**  
**Remote:** `https://github.com/Usmansayed/new-context-engine.git`  
**Package:** scubiee **v0.3.5** (+ uncommitted fixes pushed in this handoff)  
**Prior handoff:** [session-handoff-aug24-2026.md](./session-handoff-aug24-2026.md)

---

## MacBook — start here (repo already cloned)

```bash
cd ~/path/to/context-engine   # you already have this repo

git pull origin main

uv tool install --force .
export PATH="$HOME/.local/bin:$PATH"
scubiee --version

# Run tests (see below)
```

No need to re-clone. After pull, reinstall the local package so `scubiee` on PATH picks up fixes (`--help`, Copilot `.mcp.json` disconnect, etc.).

---

## What this session was about

Windows-side validation of **lifecycle CLI** (stop / halt / wipe / resume) and **connect MCP merge safety** (add/remove Scubiee without breaking neighbor servers like a mock Figma MCP). All tests use **real `scubiee` commands** in the terminal — not `python scripts/run_cli_combination_tests.py`.

**Your job on Mac:** `git pull`, reinstall, run the test scripts, paste logs back.

**Do not set `CTX_HOME`** unless you want an isolated fake home. Windows tests used real `~/.scubiee`.

---

| Fix | File | What |
|-----|------|------|
| `scubiee --help` crash | `packages/pipeline/__main__.py` | `%APPDATA%` → `%%APPDATA%%` in unlock-tool help (argparse format bug) |
| Copilot disconnect left Scubiee in root `.mcp.json` | `rules_installer.py`, `tool_registry.py` | Root file is named `.mcp.json` (`path.name` ≠ `mcp.json`); now match by resolved path |
| Continue YAML stub on wipe/halt | `process_control.py` | (from earlier in session) stub `.continue/mcpServers/scubiee.yaml` |

After pull: `uv tool install --force .` so the Mac binary includes fixes.

---

## Test suite 1 — Lifecycle E2E (real CLI)

**Purpose:** stop, block, halt, repo wipe, full wipe, cold re-init.  
**Doc:** [scubiee-cli-e2e-manual-test.md](./scubiee-cli-e2e-manual-test.md)  
**Script:** `tests/_e2e_run_cmds.sh`

```bash
chmod +x tests/_e2e_run_cmds.sh
bash tests/_e2e_run_cmds.sh
# Log: tests/_e2e_cmd_results.txt
```

### Windows results (2026-08-30)

| ID | Command | Exit | Result |
|----|---------|------|--------|
| B1 | `scubiee --version` | 0 | OK |
| B7–B10 | `setup --repair`, `init .`, `status .` | 0 | OK |
| G1–G3 | `stop -y`, `stop -y`, `init .` | 0/0/1 | stop OK, init **blocked** |
| G5,G12 | `setup --repair`, `doctor` after stop | 0 | OK (repair + read-only) |
| G14,G17,G18 | `halt`, `resume`, `init .` | 0 | OK |
| H1,H2 | `halt`, `resume` | 0 | OK |
| W1 | `wipe . --confirm` | 0 | OK; `.scubiee/id.json` removed |
| W1b | `init .` after repo wipe | 0 | OK |
| G16 | `wipe --all` | 2 | OK (safety gate) |
| G16b | `wipe --all --confirm --keep-package` | 0 | OK; `~/.scubiee` gone |
| P1–P3 | `setup --repair`, `init .`, `status .` | 0 | OK after full wipe |
| R1 | `scubiee --help` | 1 | **FAIL on old build** — fixed in source |
| R2–R4 | subcommand help, `list` | 0 | OK |

**Runtime:** ~35 min (mostly `init` indexing this repo).

### Mac notes

- Paths: `~/.scubiee`, `~/.cursor/mcp.json`, `/tmp/fastembed_cache` (model cache).
- First `setup` may need `scubiee setup --repair` if symlink/cache errors (WinError 1314 equivalent on Mac is rare but `--repair` is the escape hatch).
- After `wipe --all`, run `scubiee connect --cursor` (or your IDE) to restore MCP.

---

## Test suite 2 — Connect dry-run (real CLI)

**Purpose:** verify all 13 tools would write correct project-local MCP paths (no disk writes).  
**Doc:** [scubiee-connect-e2e-manual-test.md](./scubiee-connect-e2e-manual-test.md)  
**Script:** `tests/_e2e_run_connect.sh`

```bash
bash tests/_e2e_run_connect.sh
# Log: tests/_connect_e2e_results.txt
# JSON: tests/_connect_dry_run.json
```

### Windows result

`scubiee connect --all --dry-run` → **13/13 ok**, exit 0.

Priority tools to spot-check manually after real connect:

```bash
scubiee connect --cursor
scubiee connect --claude-code --codex --opencode --pi
# Restart each app; confirm MCP green / tools listed
```

**OpenCode watch item:** Scubiee emits v1 shape (`mcp.scubiee` with `environment`). OpenCode v2 docs use `mcp.servers.{name}`. Test with your installed OpenCode version.

**MCP format research:** [connect-global-mcp-research.md](./connect-global-mcp-research.md)

---

## Test suite 3 — MCP merge with mock neighbor (real CLI)

**Purpose:** seed mock **Figma** MCP next to Scubiee; connect/disconnect must keep valid JSON/TOML/YAML and preserve neighbor.

```bash
python3 tests/_e2e_mcp_merge_experiment.py
# Log: tests/_mcp_merge_cli_results.txt
```

### Windows result (2026-08-30): **13/13 passed**

| Tool | Mock neighbor file | After connect | After disconnect |
|------|-------------------|---------------|------------------|
| cursor | `.cursor/mcp.json` | figma + scubiee | figma only |
| claude-code | `.mcp.json` | both | figma only |
| codex | `.codex/config.toml` | both `[mcp_servers.*]` | figma table kept |
| kiro | `.kiro/settings/mcp.json` | both | figma only |
| devin-desktop | `.devin/mcp_config.json` | both | figma only |
| **copilot** | `.vscode/mcp.json` + `.mcp.json` | both paths | both cleaned (**bug fixed this session**) |
| cline | `.cline/mcp.json` | both | figma only |
| roo-code | `.roo/mcp.json` | both | figma only |
| continue | `.continue/mcpServers/figma.yaml` | + `scubiee.yaml` | neighbor yaml kept |
| zed | `.zed/settings.json` | both under `context_servers` | figma only |
| opencode | `opencode.json` | both under `mcp` | figma only |
| amp | `.amp/settings.json` | both under `amp.mcpServers` | figma only |
| pi | `.mcp.json` | both | figma only |

---

## Test suite 4 — Unit tests (pytest, optional on Mac)

Fast sanity before/after Mac CLI runs:

```bash
cd ~/path/to/context-engine
python3 -m pytest tests/test_mcp_config_merge.py -q          # 20 tests — merge safety all 13 tools
python3 -m pytest tests/test_install_health.py::test_top_level_help_does_not_crash -q
python3 -m pytest tests/test_lifecycle_guard.py tests/test_wipe.py tests/test_process_control.py -q
```

### Windows pytest (merge)

- `test_mcp_config_merge.py`: **20 passed** (includes new `test_copilot_remove_workspace_mcp_dotfile_name`)
- Parametrized `test_write_remove_roundtrip_preserves_other_servers` covers all 13 slugs with mock `my-local-mcp`

---

## Mac sign-off checklist

Copy and tick when done:

### Lifecycle
- [ ] `bash tests/_e2e_run_cmds.sh` — paste `tests/_e2e_cmd_results.txt`
- [ ] `scubiee --help` exits 0 (after reinstall from fixed source)
- [ ] `wipe --all --confirm --keep-package` removes `~/.scubiee`
- [ ] `setup --repair` + `init .` works after full wipe

### Connect
- [ ] `bash tests/_e2e_run_connect.sh` — 13/13 dry-run ok
- [ ] Real `scubiee connect --cursor` → MCP works in Cursor after restart
- [ ] (Optional) Real connect for Claude Code, Codex, OpenCode, Pi

### MCP merge
- [ ] `python3 tests/_e2e_mcp_merge_experiment.py` — 13/13 passed
- [ ] Manually inspect one file, e.g. `cat .cursor/mcp.json | python3 -m json.tool`

### Report back
- [ ] Attach or paste: `_e2e_cmd_results.txt`, `_mcp_merge_cli_results.txt`
- [ ] Note macOS version, OpenCode version (if tested), any IDE-specific issues

---

## Suggested Mac run order (single session)

```bash
export PATH="$HOME/.local/bin:$PATH"
cd ~/path/to/context-engine
uv tool install --force .

# ~1 min — merge safety (destructive to repo MCP files; run on test clone if preferred)
python3 tests/_e2e_mcp_merge_experiment.py

# ~1 min — connect dry-run
bash tests/_e2e_run_connect.sh

# ~35 min — full lifecycle (includes wipe — use test clone or accept clean slate)
bash tests/_e2e_run_cmds.sh

# Real IDE smoke
scubiee connect --cursor
# restart Cursor, run one MCP tool (e.g. map/status)
```

Use a **throwaway clone** of the repo if you do not want `wipe --all` on your main dev machine.

---

## Key files added/updated this session

| Path | Role |
|------|------|
| `docs/scubiee-cli-e2e-manual-test.md` | Lifecycle CLI test guide (Mac/Win/Linux) |
| `docs/scubiee-connect-e2e-manual-test.md` | Connect + merge test guide |
| `docs/connect-global-mcp-research.md` | OpenCode v2 note added |
| `tests/_e2e_run_cmds.sh` | Lifecycle CLI runner (bash) |
| `tests/_e2e_run_cmds.ps1` | Lifecycle CLI runner (Windows) |
| `tests/_e2e_run_connect.sh` | Connect dry-run runner |
| `tests/_e2e_mcp_merge_experiment.py` | **13-tool** Figma neighbor CLI experiment |
| `tests/_e2e_mcp_merge_experiment.sh` | Bash wrapper for merge experiment |
| `tests/test_mcp_config_merge.py` | + copilot `.mcp.json` regression test |
| `tests/test_install_health.py` | + `--help` regression test |
| `packages/pipeline/__main__.py` | `%%APPDATA%%` help fix |
| `packages/pipeline/rules_installer.py` | Copilot root `.mcp.json` disconnect fix |
| `packages/pipeline/tool_registry.py` | Copilot path resolution fix |

---

## Known limitations / not tested on Mac yet

1. **Real IDE connect** — dry-run + merge CLI only; Cursor/Claude/etc. restart not validated on macOS this session.
2. **OpenCode v2** schema — may need adapter if your OpenCode build expects `mcp.servers`.
3. **`uv tool install` file locks** — on Windows, run `scubiee halt` before reinstall if Access denied; same may apply if MCP processes hold the binary open.
4. **Pi** — requires `pi install npm:pi-mcp-adapter` for MCP in Pi terminal.
5. **Automated script** `scripts/run_cli_combination_tests.py` — still exists but **not** the source of truth; use bash/python runners above.

---

## Architecture reminder (connect)

```
scubiee init .          → enroll repo (.scubiee/id.json)
scubiee connect --X     → project-local MCP + GATE rules (fans out to all enrolled repos)
                          → removes legacy ~/.cursor/mcp.json etc.
IDE restart               → picks up .cursor/mcp.json (or tool-specific path)
scubiee disconnect --X  → removes only "scubiee" key; preserves neighbor servers
```

Project-local MCP paths: see table in [scubiee-connect-e2e-manual-test.md](./scubiee-connect-e2e-manual-test.md).

---

## Contact / context

Windows session validated lifecycle + merge CLI. MacBook session should confirm parity, especially:

- Copilot dual-path disconnect (`.vscode/mcp.json` + `.mcp.json`)
- Codex TOML merge on macOS paths
- Full wipe + re-init on Apple Silicon (MLX model path vs Windows ORT)

When Mac testing is done, update this doc with a **Mac results** section or open a PR with log files under `tests/`.
