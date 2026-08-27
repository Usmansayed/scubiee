# Install, upgrade, and debug (end users)

Complete operator guide for **installing**, **upgrading**, and **fixing** Scubiee when something goes wrong.

**Current release:** [scubiee 0.2.87](https://pypi.org/project/scubiee/0.2.87/) — live on PyPI (`uv tool install scubiee==0.2.87`).

**Names that matter:** MCP key **`scubiee`**, home **`~/.scubiee`**, repo **`<repo>/.scubiee`**. Fresh installs do not use or migrate `.context-engine`.

---

## Canonical install (every new machine)

```text
1. Install CLI
2. Machine setup (once)
3. Init repo (per project)
4. Connect IDE (per tool / Special-4 per repo)
5. Reload MCP in the IDE
```

### Windows (PowerShell)

```powershell
# 1. CLI (pin version + PyPI)
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
uv tool update-shell
# open a NEW terminal, then:

# 2. Machine (GPU/CPU, FastEmbed, model, accel.json)
scubiee setup --repair

# 3. Project
cd C:\path\to\your\repo
scubiee init .

# 4. IDE wiring (MCP + agent rules)
scubiee connect --cursor

# 5. Cursor → Settings → MCP → refresh (or restart Cursor)
```

### macOS / Linux

```bash
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
uv tool update-shell
# new shell:
scubiee setup --repair
cd /path/to/your/repo
scubiee init .
scubiee connect --cursor
# reload MCP in the IDE
```

### Alternative: pip

```bash
pip install -U scubiee==0.2.87
scubiee setup --repair
```

Prefer **uv tool install** on Windows — clearer upgrades and fewer PATH collisions.

### Verify

```bash
scubiee --version          # should print 0.2.87 and the uv-tool Python path
scubiee setup --status
scubiee doctor .
scubiee diagnose --no-tests --desktop   # → Desktop/scubiee-diagnose.json
```

In the agent: call MCP **`status()` once**. Expect `managed: true`, `ok: true` after init + connect + reload.

The MCP server key in `mcp.json` is **`scubiee`**.

---

## What each step does (do not skip)

| Step | Command | Scope | Writes |
|------|---------|-------|--------|
| Install | `uv tool install scubiee==0.2.87` | Machine | CLI + uv tool env |
| Setup | `scubiee setup --repair` | Machine | ORT/FastEmbed extras, model, `~/.scubiee/accel.json` |
| Init | `scubiee init .` | **This repo** | Index + `.scubiee/id.json` — **not** MCP |
| Connect | `scubiee connect --cursor` | IDE | MCP + agent rules |
| Reload | IDE MCP refresh | Session | Agent can see the server |

**Common mistake:** running only `init` then wondering why Cursor is unmanaged → you still need **`connect`** + reload MCP.

**Special-4** (run `connect` **inside each project**): Kiro, Copilot/VS Code, Cline, Roo Code.

**Cursor:** also writes project `.cursor/mcp.json` with an absolute repo pin. Global `~/.cursor/mcp.json` does **not** use unexpanded `${workspaceFolder}` tokens (Cursor leaves them literal → wrong home folder). Always `connect --cursor` from the project you care about.

---

## Upgrade to a new version

```powershell
# Preferred
scubiee upgrade
# or pin explicitly:
scubiee unlock-tool          # Windows if Access denied / half-broken tool dir
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor     # refresh MCP + rules after every bump
```

If `uv` briefly says “no version 0.2.87” right after a release, wait a few minutes or use `--refresh`. The [project page / files](https://pypi.org/project/scubiee/#files) are authoritative.

After upgrade: **always** `setup --repair` if FastEmbed/ORT look missing, then **`connect`** again.

---

## Debug map (symptom → fix)

### 1) `uv tool install` → Access denied (os error 5) — Windows

**Symptom:**

```text
failed to remove directory ...\uv\tools\scubiee\Scripts: Access is denied. (os error 5)
```

Later: `No module named 'pipeline'` or `uv trampoline failed to canonicalize script path`.

**Cause:** File **locks**, not permissions. Cursor MCP / daemon hold `python.exe` under `%APPDATA%\uv\tools\scubiee`. Admin PowerShell and reboot are **not** the primary fix.

**Fix (CLI still works):**

```powershell
scubiee unlock-tool
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor
```

`unlock-tool` disables MCP (so Cursor cannot respawn), stops lockers, and frees the tool directory (rename-aside if needed). Then reinstall.

**Fix (CLI already broken — no `pipeline`):**

```powershell
# From a clone that has the scripts, or download them:
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
# or repair + reinstall:
powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1 0.2.87
scubiee setup --repair
scubiee connect --cursor
```

Scripts turn MCP off **first**, then kill processes, then retry delete. Do **not** lead with Admin or reboot.

Details: [Windows guide](./windows.md) · [Uninstall on Windows](./uninstall-windows.md)

---

### 2) `No module named 'pipeline'` / broken shim

**Cause:** Half-deleted uv tool env (install interrupted by locks).

**Fix:** Same as Access denied → `unlock-tool` (if possible) or `scripts/uninstall-uv-scubiee.ps1` / `repair-uv-scubiee.ps1` → reinstall → `setup --repair`.

---

### 3) `machine_not_setup` on `init`

```bash
scubiee setup --repair
scubiee setup --status
scubiee init .
```

---

### 4) Diagnose looks fine but `init` / preflight still fail after reinstall

Stale `accel.json` while FastEmbed/ORT were wiped.

```bash
scubiee setup --repair
scubiee diagnose --no-tests --desktop
scubiee init .
```

---

### 5) Agent `status()` → `managed: false`

1. `cd` into the **project** (not your home folder)  
2. `scubiee init .` if not enrolled  
3. `scubiee connect --cursor` (or `--kiro` / `--copilot` / …)  
4. Reload MCP  
5. Ask the agent to call `status()` **once** again  

Cursor: confirm project `.cursor/mcp.json` has an absolute `CTX_REPO` for this repo.

---

### 6) Agent `warming: true`

Daemon starting. Use tools; wait a few seconds and retry the **tool** once. Do **not** poll `status()` every turn.

```bash
scubiee engine ensure . --wait 45
```

---

### 7) Search misses fresh edits

```bash
scubiee sync .
```

Put a unique string in a **`.py`** file in scope, sync, search for that token.

---

### 8) Wrong Python / conda vs uv

`scubiee --version` prints which Python runs Scubiee. Prefer  
`…\uv\tools\scubiee\Scripts\python.exe` (Windows). Do not `pip install` into conda expecting the uv tool CLI to change.

---

### 9) GPU / CPU profile wrong

| Hardware | Profile |
|----------|---------|
| Discrete NVIDIA/AMD (Windows) | `dml` |
| Intel iGPU / AMD APU only | `cpu` |
| Apple Silicon | `mlx` |

```bash
scubiee setup --status
scubiee setup --profile cpu --repair    # force CPU
scubiee setup --profile dml --repair    # discrete AMD escape hatch
scubiee setup --profile mlx --repair    # Apple Silicon
```

---

### 10) Full uninstall

```bash
scubiee stop
# quit Cursor / disable MCP
scubiee wipe --all --confirm --package
```

(`--yes` is an alias of `--confirm`.) Check JSON `audit.remaining`. If the tool dir is still locked: `scubiee unlock-tool` or the Windows PS1 scripts.

---

## Triage checklist (copy/paste)

```bash
scubiee --version
scubiee setup --status
scubiee preflight .
scubiee doctor .
scubiee list
scubiee diagnose --no-tests --desktop
```

Share `Desktop/scubiee-diagnose.json` plus a short description of the failing command.

---

## Commands that matter for install health

| Command | When |
|---------|------|
| `scubiee unlock-tool` | Windows Access denied / free `%APPDATA%\uv\tools\scubiee` |
| `scubiee upgrade` | Upgrade with pre-stop / unlock path |
| `scubiee setup --repair` | After every broken reinstall or missing FastEmbed |
| `scubiee stop` / `scubiee resume` | Pause globally / continue (not `wake`) |
| `scubiee connect --…` | After install, upgrade, or unmanaged agent |
| `scubiee engine ensure . --wait 45` | Daemon not warm |
| `scubiee wipe --all --confirm --package` | Nuclear uninstall |

Full flag list: [Commands reference](./commands-reference.md).

---

## Related guides

- [Getting started](./getting-started.md)
- [Windows](./windows.md) · [Uninstall Windows](./uninstall-windows.md)
- [Mac & Linux](./mac-and-linux.md)
- [Cursor & MCP](./cursor-mcp.md)
- [Troubleshooting](./troubleshooting.md)
- [FAQ](./faq.md)
