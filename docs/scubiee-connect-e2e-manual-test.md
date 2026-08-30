# Scubiee connect — MCP format research & manual E2E test

How `scubiee connect` writes MCP + rules for each AI coding tool, what was tested, and how to repeat on **macOS** (or Linux/Windows).

**Related:**
- Lifecycle/wipe E2E: [scubiee-cli-e2e-manual-test.md](./scubiee-cli-e2e-manual-test.md)
- Full format research (paths + schemas): [connect-global-mcp-research.md](./connect-global-mcp-research.md)
- Automated schema unit tests: `tests/test_connect_formats.py`

---

## Honest status (as of 2026-08-30)

| Layer | What ran | Result |
|-------|----------|--------|
| **Unit tests** | Per-tool MCP JSON/TOML/YAML shaping, project paths, legacy cleanup | Pass in CI / pytest |
| **Connect dry-run** | `scubiee connect --all --dry-run` (13 tools) | Exit 0, all `ok: true` on Windows |
| **Real connect E2E** | Actually writing MCP files + opening each IDE | **Not yet** in the lifecycle E2E sweep |
| **Web research** | Official docs cross-check (Aug 2026) | Matches repo research doc; see gaps below |

The lifecycle E2E script (`tests/_e2e_run_cmds.sh`) previously skipped `connect` because it mutates IDE config and needs a restart to verify. This doc adds a **connect phase** you should run on your MacBook.

---

## Design (current Scubiee behavior)

1. **`scubiee connect --<tool>`** writes **project-local MCP** under each enrolled repo (fan-out from registry).
2. **Global user MCP** in `~/.cursor/mcp.json`, `~/.claude.json`, etc. is **removed** (legacy migration — project-local is canonical).
3. **GATE rules** go to repo paths (e.g. `.cursor/rules/scubiee.mdc`, `AGENTS.md`).
4. **`CTX_REPO`** is pinned in project MCP env so the server knows which repo to serve.
5. **`--dry-run`** prints JSON of what would be written without touching disk.

Supported tools (13): `cursor`, `claude-code`, `codex`, `kiro`, `devin-desktop` (`--windsurf`), `copilot`, `cline`, `roo-code`, `continue`, `zed`, `opencode`, `amp`, `pi`.

---

## Per-tool MCP cheat sheet (macOS paths)

Paths below are **project-local** (under repo root) unless noted. Schema = what Scubiee writes.

| Tool | Project MCP file | Schema key | Shape |
|------|------------------|------------|-------|
| **Cursor** | `.cursor/mcp.json` | `mcpServers` | `{ command, args, env }` — [Cursor MCP docs](https://cursor.com/docs/mcp) |
| **Claude Code** | `.mcp.json` | `mcpServers` | Same Claude-style stdio — [Claude Code MCP](https://code.claude.com/docs/en/mcp) |
| **Codex** | `.codex/config.toml` | `[mcp_servers.scubiee]` | TOML: `command`, `args`, `env`, optional `cwd` — [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp.md) |
| **OpenCode** | `opencode.json` | `mcp.scubiee` | `type: local`, `command: []`, **`environment`** (not `env`) — [OpenCode MCP](https://opencode.ai/docs/mcp-servers/) |
| **Amp** | `.amp/settings.json` | `"amp.mcpServers"` | Dotted key at top level — [Amp MCP manual](https://ampcode.com/manual/mcp.md) |
| **Pi** | `.mcp.json` | `mcpServers` | Claude-style; needs `pi-mcp-adapter` — [Pi MCP adapter](https://nicobailon-pi-mcp-adapter.mintlify.app/introduction) |
| **Continue** | `.continue/mcpServers/scubiee.yaml` | YAML list item | `name`, `command`, `args`, `env` |
| **Zed** | `.zed/settings.json` | `context_servers` | `{ command, args, env }` |
| **Kiro** | `.kiro/settings/mcp.json` | `mcpServers` | Claude-style |
| **Copilot** | `.vscode/mcp.json` + `.mcp.json` | `servers` / `mcpServers` | VS Code uses `type: stdio`; root `.mcp.json` Claude-style |
| **Cline** | `.cline/mcp.json` | `mcpServers` | Claude-style |
| **Roo Code** | `.roo/mcp.json` | `mcpServers` | Claude-style |
| **Devin Desktop** | `.devin/mcp_config.json` | `mcpServers` | Claude-style |

**Linux:** same home-relative paths (`~/.config/...`).  
**Windows:** `%USERPROFILE%` instead of `~`; Zed uses `%APPDATA%\Zed\settings.json`.

---

## Web research notes (Aug 2026)

Cross-checked against official docs. Scubiee’s adapters match current public formats for:

- **Cursor** — `mcpServers` + `command`/`args`/`env` in `.cursor/mcp.json` or `~/.cursor/mcp.json`
- **Claude Code** — `.mcp.json` (project) or top-level `mcpServers` in `~/.claude.json` (user scope)
- **Codex** — `[mcp_servers.name]` tables in TOML (underscore, not dot)
- **OpenCode v1** — top-level `mcp.{name}` with `type: local`, `command` array, `environment`
- **Pi** — standard `mcpServers`; adapter reads `.mcp.json` at project root

### Known gaps / watch items

1. **OpenCode v2** — newer docs use `mcp.servers.{name}` and `disabled` instead of `enabled`. Scubiee still emits **v1** shape (`mcp.scubiee`). Test with your OpenCode version on Mac; if MCP missing, we may need a v2 adapter or dual-write.
2. **Pi global path** — Scubiee also documents `~/.pi/agent/mcp.json`; pi-mcp-adapter **prefers** project `.mcp.json`. Project-local connect (current behavior) is correct for Pi.
3. **Codex transport** — newest Codex builds support nested `transport = { type = "stdio", ... }`. Scubiee uses flat `command`/`args`/`env` which remains valid per OpenAI docs.
4. **IDE restart** — all hosts need reload/restart after MCP file changes (Cursor: Settings → MCP toggle or restart).

---

## macOS: prerequisites

```bash
cd ~/path/to/context-engine
uv tool install --force .
export PATH="$HOME/.local/bin:$PATH"

# Must be enrolled first
scubiee setup --repair
scubiee init .
```

---

## Phase A — Dry-run (safe, no disk writes)

Run from repo root. Expect exit **0** and `"ok": true` for every tool.

```bash
# Priority tools you asked about
scubiee connect --cursor --claude-code --codex --opencode --amp --pi --dry-run

# All 13 tools
scubiee connect --all --dry-run > tests/_connect_dry_run.json
python3 -c "
import json, sys
data = json.load(open('tests/_connect_dry_run.json'))
assert all(x.get('ok') for x in data), [x for x in data if not x.get('ok')]
print(f'OK: {len(data)} tools')
for x in data:
    print(f\"  {x['slug']:16} -> {x.get('mcp_path','')}\")
"
```

**Pass if:** each entry lists a project `mcp_path` under your repo and `project_fan_out.repos >= 1`.

---

## Phase B — Real connect (one tool at a time)

Pick tools you actually have installed. After each connect, **restart that app** and confirm Scubiee MCP appears.

### Cursor (most common)

```bash
scubiee connect --cursor
cat .cursor/mcp.json          # should contain mcpServers.scubiee
cat .cursor/rules/scubiee.mdc # GATE rule with project_id
# Restart Cursor → Settings → MCP → scubiee green
```

### Claude Code

```bash
scubiee connect --claude-code
cat .mcp.json                   # project-local mcpServers
grep scubiee ~/.claude/CLAUDE.md 2>/dev/null || true
claude mcp list                 # optional: verify Claude sees server
```

### Codex

```bash
scubiee connect --codex
grep -A5 'mcp_servers.scubiee' .codex/config.toml
grep scubiee ~/.codex/AGENTS.md 2>/dev/null || true
codex mcp list                  # optional
```

### OpenCode

```bash
scubiee connect --opencode
cat opencode.json | python3 -m json.tool | head -40
# Look for: "type": "local", "command": [...], "environment": { "CTX_REPO": "..." }
opencode                          # open TUI, check MCP panel
```

### Amp

```bash
scubiee connect --amp
python3 -c "import json; print(json.dumps(json.load(open('.amp/settings.json')), indent=2))" | grep -A3 amp.mcpServers
```

### Pi

```bash
pi install npm:pi-mcp-adapter    # if not installed
scubiee connect --pi
cat .mcp.json
pi                               # /mcp panel should list scubiee
```

---

## Phase C — Verify MCP entry shape

After real connect, spot-check one file per tool:

```bash
# Cursor / Claude / Pi — JSON mcpServers
python3 <<'PY'
import json, pathlib
for p in [".cursor/mcp.json", ".mcp.json"]:
    f = pathlib.Path(p)
    if f.exists():
        s = json.loads(f.read_text())["mcpServers"]["scubiee"]
        assert "command" in s and "args" in s
        assert "CTX_REPO" in s.get("env", {})
        print(p, "OK", s["command"], s["args"][:2])
PY

# Codex — TOML
grep -E '^(command|args|\[mcp_servers)' .codex/config.toml 2>/dev/null | head -10

# OpenCode
python3 -c "
import json
o=json.load(open('opencode.json'))
e=o['mcp']['scubiee']
assert e['type']=='local' and 'environment' in e
print('opencode OK', e['command'][:3])
"
```

**Pass if:** `command`/`args` point at your Python/uv tool interpreter and `env` includes `CTX_REPO` with this repo’s absolute path.

---

## Phase D — Disconnect / reconnect

```bash
scubiee disconnect --cursor
test ! -f .cursor/mcp.json && echo "cursor MCP removed OK"

scubiee connect --cursor
test -f .cursor/mcp.json && echo "cursor MCP restored OK"
```

---

## Phase E — Connect after stop / wipe

| Scenario | Command | Expect |
|----------|---------|--------|
| After `stop` | `scubiee connect --cursor` | Auto-resumes then connects (exit 0) |
| After `wipe .` | `scubiee connect --cursor` | Need `init .` first |
| After `wipe --all` | `scubiee setup && init . && connect --cursor` | Full cold path |

---

## Automated runner (connect dry-run only)

Append to lifecycle E2E or run standalone:

```bash
bash tests/_e2e_run_connect.sh
```

Logs: `tests/_connect_e2e_results.txt`

---

## Windows reference (2026-08-30)

```
scubiee connect --all --dry-run  → 13 tools, exit 0, all ok
```

Sample project paths written (repo: `context-engine`):

| slug | mcp_path |
|------|----------|
| cursor | `.cursor/mcp.json` |
| claude-code | `.mcp.json` |
| codex | `.codex/config.toml` |
| opencode | `opencode.json` |
| amp | `.amp/settings.json` |
| pi | `.mcp.json` |
| continue | `.continue/mcpServers/scubiee.yaml` |
| zed | `.zed/settings.json` |

Full JSON: `tests/_connect_dry_run.json` (generate on your machine).

---

## Checklist for MacBook sign-off

Copy to your notes and tick when done:

- [ ] `connect --all --dry-run` → 13/13 ok
- [ ] `connect --cursor` → MCP green in Cursor after restart
- [ ] `connect --claude-code` → `.mcp.json` + Claude sees tools
- [ ] `connect --codex` → TOML block in `.codex/config.toml`
- [ ] `connect --opencode` → `opencode.json` with `environment` key
- [ ] `connect --amp` → `amp.mcpServers` in `.amp/settings.json`
- [ ] `connect --pi` → `.mcp.json` + `/mcp` in Pi (with adapter)
- [ ] `disconnect --cursor` removes `.cursor/mcp.json`
- [ ] `connect --cursor` after `stop -y` works (auto-resume)

Paste your `tests/_connect_e2e_results.txt` or `_connect_dry_run.json` when reporting back.

---

## MCP merge safety (Figma-style mock)

**Question:** If `mcp.json` already has another server (e.g. Figma MCP), does `connect` / `disconnect` leave valid JSON and keep the other server?

**Unit tests:** `tests/test_mcp_config_merge.py` — parametrized over **all 13 tools** with a mock `my-local-mcp` neighbor. Also refuses corrupt JSON (won't overwrite broken files). **19 tests pass.**

**Real CLI experiment:** `tests/_e2e_mcp_merge_experiment.py` seeds a **Figma-like** mock, then runs actual `scubiee connect` / `disconnect`:

```bash
python3 tests/_e2e_mcp_merge_experiment.py
# or: bash tests/_e2e_mcp_merge_experiment.sh
```

| Tool | Mock file | After connect | After disconnect |
|------|-----------|---------------|------------------|
| Cursor | `.cursor/mcp.json` (remote Figma URL) | `figma` + `scubiee` | `figma` only, valid JSON |
| Claude Code | `.mcp.json` (stdio Figma) | both present | `figma` only |
| OpenCode | `opencode.json` | both under `mcp` | `figma` only |
| Codex | `.codex/config.toml` | both `[mcp_servers.*]` | Figma table kept, valid TOML |

**Windows run (2026-08-30):** all four passed — no syntax/structure breakage.

**Not covered in CLI experiment yet:** Copilot dual-path, Continue YAML, Zed, Amp dotted key — but unit tests cover all 13 slugs via `test_write_remove_roundtrip_preserves_other_servers`.
