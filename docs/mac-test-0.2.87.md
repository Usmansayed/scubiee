# macOS test plan — Scubiee 0.2.87

**Date:** 2026-08-27  
**Release:** [scubiee 0.2.87 on PyPI](https://pypi.org/project/scubiee/0.2.87/)  
**Git:** `da206db` on `main` (`new-context-engine`)  
**Who:** Mac validation after Windows wipe + production publish  

Use this on **Apple Silicon** (preferred) or Intel Mac. Goal: confirm the Scubiee-only branding cut and Cursor MCP work end-to-end.

---

## What changed (why Mac should re-test)

### Product identity (breaking vs older builds)

| Before (legacy) | Now (0.2.87) |
|-----------------|--------------|
| MCP key `context-engine` | MCP key **`scubiee`** |
| `~/.context-engine/` | **`~/.scubiee/`** |
| `<repo>/.context-engine/` | **`<repo>/.scubiee/`** |
| Rules `context-engine.mdc` / old markers | **`scubiee.mdc`** / `<!-- scubiee:start -->` |
| Legacy home/MCP migration helpers | **Removed** — fresh Scubiee only |

There is **no** automatic migrate from `.context-engine` → `.scubiee`. Treat this as a clean install.

### Cursor / MCP (still important on Mac)

- Global `~/.cursor/mcp.json` must **not** use unexpanded `${workspaceFolder}` for `CTX_REPO`.
- `connect --cursor` writes **project** `.cursor/mcp.json` with an **absolute** `CTX_REPO` (+ `CTX_PROJECT_ID`).
- Health / MCP server name reports **`scubiee`**.

### Mac accel (unchanged intent, still verify)

- Apple Silicon → profile **`mlx`** after `setup --repair` (must not stay on CPU).
- Intel Mac → `coreml` or `cpu`.

### Docs

- User guides under `docs/web-info/` pinned to **0.2.87** (install, Mac/Linux, Cursor, wipe with `--confirm`).

---

## What you should test on Mac

Priority order:

1. **Clean install from PyPI** (not a dirty local editable install).
2. **Branding paths + MCP key** (no leftover `context-engine`).
3. **Apple Silicon = MLX**.
4. **Cursor project pin** → `status()` → `managed: true`.
5. **Locate smoke** (`map` / `grep` / `glob`).
6. **Optional:** wipe + reinstall once.

Windows-only items you can skip: `unlock-tool`, Access denied on `%APPDATA%\uv\tools\…`.

---

## How to test (copy/paste)

### 0) Prep — remove old identity if present

```bash
# Optional but recommended if you used older builds on this Mac:
scubiee stop 2>/dev/null || true
# Quit Cursor (or disable MCP) so files are not locked.

# If an older CLI still works:
scubiee wipe --all --confirm --package 2>/dev/null || true

# Manual leftovers (safe if Scubiee is stopped):
rm -rf ~/.context-engine ~/.scubiee
# In each old test repo:
#   rm -rf .context-engine .scubiee
# Strip old MCP keys from ~/.cursor/mcp.json if present (key must be "scubiee" only).
```

### 1) Install 0.2.87 from PyPI

```bash
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
uv tool update-shell
# open a NEW terminal
scubiee --version
# Expect: scubiee 0.2.87  (and a uv-tools Python path)
which scubiee
which scubiee-mcp
```

**Pass:** version is exactly `0.2.87`.

### 2) Machine setup (MLX on Apple Silicon)

```bash
scubiee setup --repair
scubiee setup --status
```

**Pass (Apple Silicon):**

- Profile / provider shows **`mlx`** (not stuck on `cpu`).
- Model + calibration complete without hanging.

**Pass (Intel):** `coreml` or `cpu` is fine; note which one.

If stuck on CPU on Apple Silicon:

```bash
scubiee setup --profile mlx --repair
scubiee setup --status
```

### 3) Index a real repo

```bash
cd /path/to/some/git/repo   # not $HOME
scubiee init .
scubiee doctor .
scubiee status .
```

**Pass:**

- `init` succeeds (or asks `--confirm` only for huge scopes — that is OK).
- Repo has **`.scubiee/id.json`** (and **no** new `.context-engine/`).
- Home index under **`~/.scubiee/projects/...`**.
- Daemon healthy; chunks > 0 for a non-empty repo.

### 4) Connect Cursor (critical Mac check)

```bash
cd /path/to/same/git/repo
scubiee connect --cursor
```

Inspect:

```bash
# Global — MCP key must be scubiee; no literal ${workspaceFolder} in CTX_REPO
cat ~/.cursor/mcp.json

# Project pin — absolute CTX_REPO for this repo
cat .cursor/mcp.json

# Rules
ls ~/.cursor/rules/scubiee.mdc
# or project rules if your Cursor layout uses them
```

**Pass:**

| Check | Expected |
|-------|----------|
| MCP server key | `"scubiee"` only (no `"context-engine"`) |
| Global `CTX_REPO` | absent / not a `${…}` token |
| Project `.cursor/mcp.json` | absolute path to this repo in `CTX_REPO` |
| Command | points at `scubiee-mcp` from uv tool / `~/.local/bin` |
| Rules | Scubiee markers / `scubiee.mdc` |

Then in Cursor: **Settings → MCP → refresh** (or restart Cursor).

### 5) Agent / MCP smoke (in Cursor on that repo)

In a **new** agent chat for the connected project:

1. Call **`status()`** once.
2. Call **`map`** with a short code-ish query (symbols from that repo).
3. Call **`grep`** for a known string.
4. Call **`glob`** for a known file.

**Pass:**

```text
status.managed == true
status.ok / ready / warm_state ready (or warming briefly then tools work)
map returns cards
grep/glob return hits when the string/file exists
```

**Fail (known class from earlier Mac session):** `managed: false` because global MCP still points at home / literal `${workspaceFolder}` — re-run `connect --cursor` **from the project**, reload MCP, new chat.

### 6) Health JSON branding

```bash
curl -s http://127.0.0.1:8765/health | python3 -m json.tool
```

**Pass:** `"service": "scubiee"`, `"version": "0.2.87"`, `"ok": true`.

### 7) Optional: wipe + reinstall once

```bash
scubiee stop
# quit Cursor MCP
scubiee wipe --all --confirm --package
# Confirm ~/.scubiee gone (or audit.remaining explained)
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
```

**Pass:** wipe JSON `audit` is clean or leftovers are only explainable locks; reinstall works.

---

## Quick checklist (tick on Mac)

- [ ] `scubiee --version` → `0.2.87`
- [ ] No `~/.context-engine` created by new flows
- [ ] `~/.scubiee` + `<repo>/.scubiee` exist after init
- [ ] Apple Silicon: `setup --status` → **mlx**
- [ ] `~/.cursor/mcp.json` key = **`scubiee`**
- [ ] Project `.cursor/mcp.json` has absolute `CTX_REPO`
- [ ] Cursor `status()` → `managed: true`
- [ ] `map` / `grep` / `glob` work
- [ ] `/health` → `service: scubiee`, version `0.2.87`
- [ ] (Optional) wipe `--all --confirm --package` then reinstall OK

---

## What to send back

Paste (redact absolute usernames if you want):

1. `scubiee --version`
2. `scubiee setup --status` (profile / t/s)
3. Whether Apple Silicon or Intel
4. Snippet of `~/.cursor/mcp.json` + project `.cursor/mcp.json` (env only)
5. `status()` JSON fields: `managed`, `ok`/`ready`, `warming`, `server`
6. One `map` result (file names only is enough)
7. Any failure: full command + stderr / diagnose JSON  

Share diagnostics:

```bash
scubiee diagnose --no-tests --desktop
# → Desktop/scubiee-diagnose.json
```

---

## Out of scope for this Mac pass

- Windows `unlock-tool` / Access denied
- npm package (not published)
- Publishing again (0.2.87 already on PyPI)
- Migrating old `.context-engine` data (unsupported — wipe and re-init)

---

## References

- Install playbook: [`docs/web-info/install-and-debug.md`](./web-info/install-and-debug.md)
- Mac/Linux: [`docs/web-info/mac-and-linux.md`](./web-info/mac-and-linux.md)
- Cursor MCP: [`docs/web-info/cursor-mcp.md`](./web-info/cursor-mcp.md)
- Prior Mac workspace-token notes: [`docs/mac-session-2026-08-26-workspace-token-issue.md`](./mac-session-2026-08-26-workspace-token-issue.md)
