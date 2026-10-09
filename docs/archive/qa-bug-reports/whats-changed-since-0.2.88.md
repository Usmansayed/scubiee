# What's changed since scubiee 0.2.88

**Current release:** [scubiee 0.3.13](https://pypi.org/project/scubiee/0.3.13/) (September 2026)  
**Baseline in old docs:** 0.2.88 (August 2026)

This document is for **operators upgrading** from 0.2.x or early 0.3.x. For day-to-day use after upgrade, see [web-info/README.md](./web-info/README.md).

---

## Upgrade in one minute

```bash
# Recommended
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor    # or your IDE — refresh MCP + rules
```

Then reload MCP in your IDE. Re-run `scubiee init .` only if a repo shows `enrolled: false`.

---

## Highlights (0.2.88 → 0.3.13)

| Area | Before (0.2.88 docs) | Now (0.3.13) |
|------|----------------------|--------------|
| **Version pin** | `scubiee==0.2.88` | `scubiee==0.3.13` |
| **Repo `status`** | Could show fake store/collection on never-initialized folders | `enrolled: false`, `state: "unmanaged"` when not set up |
| **Repo wipe** | Could run without confirmation | Requires TTY confirm or `--confirm` (exit **2** without) |
| **Repo wipe cleanup** | Could leave orphan VectorDB collections | Drops VectorDB + legacy index paths for that repo |
| **`pause` → `activate`** | `activate` could fail with `error: "paused"` | `activate` restores repo to **active** (0.3.11+) |
| **`sync-now` while paused** | Still ran | Blocked with `error: "paused"` — run `activate` first (0.3.13+) |
| **Global `stop`** | Process teardown could leave half-stopped state on Windows | Pause state saved **before** kill; CLI process tree protected (0.3.13+) |
| **Windows terminal** | Raw ANSI (`[90m`) on some consoles | `colorama` + UTF-8 init; branded banner; single progress bar for setup/wipe |
| **`doctor`** | Basic readiness only | Shows **active vs expected binary** when multiple installs on PATH |
| **`wipe --all --keep-package`** | Could remove CLI shims | Keeps uv tool on PATH when `--keep-package` (0.3.5+) |
| **OpenCode MCP** | v1 flat config only | v2 `mcp.servers` shape + migration (0.3.5+) |
| **Moved / renamed repos** | Stale registry paths | `fs_id` tracking + fan-out on connect/wipe (Darwin/Linux) |
| **CTX_HOME in temp** | Unrestricted | Production CLI refuses polluted temp paths; use default `~/.scubiee` |
| **Combination testing** | Import-only tests | 39-scenario real CLI matrix (`scripts/run_cli_combination_tests.py --cli`) |

---

## Release notes by version

### 0.3.13 (September 2026)

- Persist global pause state before process teardown (fixes flaky `stop -y` on Windows).
- Protect invoking CLI process tree during stop/wipe/unlock.
- Windows: `colorama`, UTF-8 console, SCUBIEE banner, single wipe progress bar.
- Block `sync-now` when repo lifecycle is **paused**.
- `doctor`: install identity (active binary, extras on PATH, upgrade hint).
- CLI combination runner: auto `CTX_ALLOW_TEST_HOME` on Windows temp homes; resume between global-stop scenarios.
- `turbo_quant`: suppress quantize warnings on tiny indexes.

### 0.3.12

- `status` honest for unmanaged repos (`enrolled: false`).
- Repo `wipe` requires confirmation (`--confirm` or TTY prompt); exit **2** when declined.
- Repo wipe drops VectorDB collections and legacy index dirs.
- `turbo_quant` dequantize edge case for 1-chunk repos.

### 0.3.11

- `scubiee activate .` after `scubiee pause .` works (transitions PAUSED → ACTIVE).
- Expanded CLI combination test runner (`--cli`, 39 scenarios).

### 0.3.5 – 0.3.10 (August 2026)

- **`wipe --all --keep-package`** no longer removes uv tool shims.
- OpenCode MCP **v2** config (`mcp.servers`) with v1 migration.
- Hardware path tracking (`fs_id`) for moved/renamed checkouts on connect and wipe.
- Darwin `F_GETPATH` fix for move detection.
- Lifecycle / upgrade registry improvements, MCP hot-reload, production hardening.
- See maintainer handoffs: [session-summary-aug31-2026-macbook.md](./session-summary-aug31-2026-macbook.md), [session-handoff-sep02-2026-macbook.md](./session-handoff-sep02-2026-macbook.md).

### 0.3.0 – 0.3.4

- Major 0.3 line: managed repo lifecycle, global stop/resume, connect/disconnect family, upgrade command, dashboard, expanded MCP tool surface.
- Product identity finalized: MCP key **`scubiee`**, data under **`~/.scubiee`** (no legacy `context-engine` paths).

---

## Commands that changed behavior

### `scubiee status [path]`

Unmanaged folder (never ran `init`):

```json
{
  "enrolled": false,
  "state": "unmanaged",
  "hint": "Run `scubiee init .` to enroll this repository."
}
```

### `scubiee wipe [path]`

Non-interactive without confirm:

```json
{
  "error": "confirm_required",
  "needs_confirm": true,
  "hint": "Re-run with: scubiee wipe <path> --confirm"
}
```

Exit code **2**. Interactive TTY shows a confirmation prompt.

### `scubiee pause .` then `scubiee activate .`

After 0.3.11, `activate` sets `state: "active"`. Use **`scubiee resume`** for **global** stop (`scubiee stop`), not per-repo pause.

### `scubiee sync-now [path]`

When repo is **paused** (0.3.13+):

```json
{
  "ok": false,
  "error": "paused",
  "hint": "Repository is paused — run `scubiee activate .` before sync-now."
}
```

### `scubiee stop` vs `scubiee engine stop`

| Command | Scope |
|---------|--------|
| `scubiee stop` | **Global** — tears down MCP/rules, hides `.scubiee`, blocks most CLI until `scubiee resume` |
| `scubiee engine stop` | **Daemon only** — MCP stays; `engine start` or MCP brings engine back |

Do not use `engine start` after global stop — use **`scubiee resume`**.

### `scubiee doctor [path]`

JSON now includes **`install`**: version, active binary, expected binary, `extra_on_path`, and hint when multiple scubiee installs are on PATH.

---

## Windows-specific

- **CPU-only laptops** (Intel UHD / AMD APU): setup uses **`cpu`** profile — no DirectML hang.
- **Terminal UX (0.3.13):** colors and progress bars work in cmd/PowerShell without raw escape codes.
- **`scubiee unlock-tool`:** still the first step for Access denied on `uv tool install`.
- **Do not set `CTX_HOME` to a temp folder** for normal use — CLI refuses polluted paths. Tests use `CTX_ALLOW_TEST_HOME=1`.

---

## MCP / connect (unchanged workflow, expanded tools)

1. `scubiee init .` — enroll + index (**does not** write MCP).
2. `scubiee connect --cursor` (or `--all`, `--kiro`, etc.) — MCP + agent rules.
3. Reload MCP in the IDE.

OpenCode users: configs are written in **v2** shape when the file is new or migrated.

---

## Testing confidence

| Platform | CLI combination matrix |
|----------|------------------------|
| macOS (Sep 2026) | 39/39 PASS |
| Windows (Sep 2026, PyPI 0.3.13) | 39/39 PASS |

Run locally:

```bash
export CTX_ALLOW_TEST_HOME=1   # Windows: required for temp CTX_HOME
python scripts/run_cli_combination_tests.py \
  --cli "$(which scubiee)" \
  --repo /path/to/tiny-repo \
  --json /tmp/cli_combo.json
```

---

## Known open items

| Issue | Workaround |
|-------|------------|
| GitHub Actions publish workflow broken on private repo | Manual `twine upload` (see [publish-setup.md](./publish-setup.md)) |
| `doctor` `expected_binary` path on Windows venv | Cosmetic; use `active_binary` + PATH hint |
| npm `scubiee` wrapper | Still not published to npm registry |

---

## Doc index

| Doc | Purpose |
|-----|---------|
| [web-info/README.md](./web-info/README.md) | User guides (updated for 0.3.13) |
| [web-info/commands-reference.md](./web-info/commands-reference.md) | Full command list |
| [web-info/install-and-debug.md](./web-info/install-and-debug.md) | Install + repair playbook |
| [session-handoff-sep02-2026-macbook.md](./session-handoff-sep02-2026-macbook.md) | 0.3.11/0.3.12 QA handoff |

---

*Last updated: September 2, 2026 — scubiee 0.3.13*
