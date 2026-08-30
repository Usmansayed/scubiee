# Scubiee CLI combination test matrix

Manual + automated checklist for **Windows, macOS, and Linux**.  
Run automated subset: `python scripts/run_cli_combination_tests.py --json /tmp/scubiee-cli-results.json`

**Real CLI e2e (recommended):** see [scubiee-cli-e2e-manual-test.md](./scubiee-cli-e2e-manual-test.md) — run `bash tests/_e2e_run_cmds.sh` on macOS or `powershell -File tests\_e2e_run_cmds.ps1` on Windows.

Use an **isolated home** when testing destructive flows:

```bash
export CTX_HOME=/tmp/scubiee-test-$$
mkdir -p "$CTX_HOME"
cd /path/to/your/repo
```

On Windows PowerShell:

```powershell
$env:CTX_HOME = "$env:TEMP\scubiee-test-$(Get-Random)"
cd C:\path\to\repo
```

---

## Legend

| Column | Meaning |
|--------|---------|
| **Expect** | What should happen |
| **Pass if** | How to mark pass on your OS |

Expect values:
- **OK** — exit 0, command succeeds
- **BLOCK** — exit 1 + message mentions `resume` or `stopped`
- **NOOP** — exit 0, already in target state
- **CONFIRM** — exit 2 or JSON `confirm_required` (wipe --all without `--confirm`)
- **ANY** — runs without crash; record exit + output |

---

## 1. Baseline (fresh / not enrolled)

| ID | Steps | Expect | Pass if |
|----|-------|--------|---------|
| B1 | `scubiee --version` | OK | prints version |
| B2 | `scubiee gate .` | OK | JSON with gate line or `0` |
| B3 | `scubiee doctor` | ANY | runs; `ok:false` if not enrolled is fine |
| B4 | `scubiee preflight` | ANY | runs; reports deps |
| B5 | `scubiee status .` | ANY | runs; shows not enrolled |
| B6 | `scubiee init .` | ANY | needs `setup` first on fresh machine |
| B7 | `scubiee setup --repair` | OK | creates `~/.scubiee/accel.json` |
| B8 | `scubiee init .` (after setup) | OK | creates `.scubiee/id.json` |
| B9 | `scubiee connect --cursor` | OK | writes MCP + rules |
| B10 | `scubiee status .` | OK | enrolled + connected hints |

---

## 2. Global stop (`scubiee stop`) combinations

Start from **READY** (setup + init + connect done).

| ID | Steps | Expect | Pass if |
|----|-------|--------|---------|
| G1 | `stop -y` | OK | MCP/rules/.scubiee removed |
| G2 | `stop -y` again | NOOP | "Already stopped" |
| G3 | `init .` after stop | BLOCK | message: run `resume` |
| G4 | `setup` after stop | BLOCK | blocked |
| G5 | `setup --repair` after stop | OK | repair allowed |
| G6 | `connect --cursor` after stop | OK | auto-resumes then connects |
| G7 | `engine start .` after stop | BLOCK | use `resume` not engine start |
| G8 | `engine status .` after stop | OK | shows globally paused |
| G9 | `engine stop` after stop | NOOP | hint: already globally stopped |
| G10 | `search . "test"` after stop | BLOCK | blocked |
| G11 | `index .` after stop | BLOCK | blocked |
| G12 | `doctor` after stop | OK | read-only allowed |
| G13 | `gate .` after stop | OK | read-only allowed |
| G14 | `halt` after stop | OK | recovery allowed |
| G15 | `wipe .` after stop | OK | repo wipe works |
| G16 | `wipe --all` after stop | CONFIRM | needs `--confirm` |
| G16b | `wipe --all --confirm --keep-package` | OK | full clean, audit clean |
| G17 | `resume` after stop | OK | restores MCP + id + engine |
| G18 | `init .` after resume | OK | idempotent / ok |

---

## 3. Engine-only stop (`scubiee engine stop`) combinations

Start from **READY**.

| ID | Steps | Expect | Pass if |
|----|-------|--------|---------|
| E1 | `engine stop` | OK | daemon down |
| E2 | `engine status .` | OK | `running:false` |
| E3 | `engine start .` | OK | daemon up |
| E4 | `init .` after engine stop | OK | **not** blocked (unlike global stop) |
| E5 | `connect --cursor` after engine stop | OK | MCP unchanged |
| E6 | `stop -y` after engine stop | OK | escalates to global stop |
| E7 | `engine ensure .` after engine stop | OK | starts daemon |

---

## 4. Wipe combinations

| ID | Steps | Expect | Pass if |
|----|-------|--------|---------|
| W1 | `wipe .` (enrolled repo) | OK | `.scubiee` gone; engine restarted |
| W2 | `wipe .` (already wiped) | OK | ok/unmanaged |
| W3 | `wipe --all` | CONFIRM | no delete without confirm |
| W4 | `wipe --all --confirm` | OK | one-shot: stub MCP, kill, unlock, wipe |
| W5 | `wipe --all --confirm --keep-package` | OK | home gone; uv tool remains |
| W6 | `halt` then `wipe --all --confirm` | OK | halt not required but harmless |
| W7 | After W4: check folders | OK | no `~/.scubiee`, no repo `.scubiee` |
| W8 | `uv tool install scubiee` after W4 | OK | reinstall works |
| W9 | `setup --repair` after W4 | OK | fresh profile |
| W10 | `init .` → `connect` after W4 | OK | back to ready |

**macOS note:** W4 should work with Cursor open (MCP stubbed to no-op). Quit IDE only if audit shows leftovers.

---

## 5. Connect / disconnect combinations

| ID | Steps | Expect | Pass if |
|----|-------|--------|---------|
| C1 | `connect --cursor` before init | ANY | MCP may pin; tools say not managed |
| C2 | `init .` after C1 | OK | enrolls repo |
| C3 | `disconnect --cursor` | OK | MCP removed; enrollment kept |
| C4 | `connect --cursor` after C3 | OK | MCP restored |
| C5 | `connect --claude-code` | OK | writes `~/.claude.json` |
| C6 | `disconnect --all` | OK | all tool MCP entries removed |

---

## 6. Repo lifecycle commands

| ID | Steps | Expect | Pass if |
|----|-------|--------|---------|
| L1 | `initialize .` | OK | same family as init |
| L2 | `activate .` | OK | per-repo active |
| L3 | `pause .` | OK | per-repo paused in registry |
| L4 | `activate .` after L3 | OK | un-pause repo |
| L5 | `list` | OK | JSON registry |
| L6 | `sync-now .` | ANY | runs or skip if no index |
| L7 | `rebuild .` | ANY | runs if enrolled |
| L8 | `remove .` | OK | unmanage repo |

---

## 7. Recovery / edge commands

| ID | Steps | Expect | Pass if |
|----|-------|--------|---------|
| X1 | `halt` | OK | MCP stub + processes stopped |
| X2 | `unlock-tool` | OK | uv dir unlocked (Windows) |
| X3 | `upgrade` | ANY | runs or reports up to date |
| X4 | `migrate --check-all` | OK | migration check |
| X5 | `diagnose --no-tests` | OK | writes log |
| X6 | `certify` | ANY | release gate |
| X7 | `stop -y` → `resume` → `engine status .` | OK | full roundtrip |

---

## 8. Wrong recovery paths (must fail safely)

| ID | Steps | Expect | Pass if |
|----|-------|--------|---------|
| X8 | `stop -y` → `engine start .` | BLOCK | tells user to use resume |
| X9 | `stop -y` → `init .` | BLOCK | tells user to use resume |
| X10 | Agent: MCP after stop (stale) | ANY | tools return `paused:true` |

---

## 9. Platform-specific checks

### Windows
- [ ] W4 with **Cursor open** — no reboot needed
- [ ] `unlock-tool` renames `%APPDATA%\uv\tools\scubiee` aside
- [ ] `taskkill` not required manually after `wipe --all`

### macOS
- [ ] W4 with **Cursor open** — MCP stub uses `/usr/bin/true`
- [ ] `uv tool install --force scubiee` after wipe
- [ ] No `Access denied` on `~/.scubiee` delete
- [ ] `scubiee --help` prints without Unicode error (UTF-8 terminal)

### Linux
- [ ] Same as macOS for halt/wipe
- [ ] systemd user supervisor if enabled

---

## 10. Automated runner (subset)

```bash
# From repo root — isolated temp CTX_HOME per run
python scripts/run_cli_combination_tests.py --json /tmp/scubiee-cli-results.json

# Skip slow wipe scenarios
python scripts/run_cli_combination_tests.py --quick
```

Record results in this table when testing macOS:

| ID | macOS date | macOS result | Notes |
|----|------------|--------------|-------|
| G1 | | | init after stop must BLOCK |
| G3 | | | setup --repair allowed when stopped |
| G4 | | | engine start after stop must BLOCK |
| E4 | | | init after engine-only stop must OK |
| W4 | | | full wipe one-shot with Cursor open |
| X8 | | | stop then engine start must BLOCK |
| … | | | |

### Windows automated run (2026-08-30)

`python scripts/run_cli_combination_tests.py` — **24/24 passed** (isolated temp `CTX_HOME`, dev tree via `python -m pipeline`).

Verified combinations include:
- `stop` → `init` **BLOCKED**
- `stop` → `setup` **BLOCKED**; `setup --repair` runs
- `stop` → `engine start` **BLOCKED**
- `stop` → `engine status` / `halt` / `wipe --all` allowed
- `stop` → `resume` OK
- `engine stop` → `init` runs (not globally blocked)
- `halt` → `wipe --all` confirm gate OK

Not covered by automated runner (manual on macOS): `search`, `index`, `sync`, `dashboard`, `serve`, `mcp`, `upgrade`, `unlock-tool`, `certify`, full `setup`+model download path.

---

## Quick smoke (5 min)

```bash
scubiee --version
scubiee setup --repair
scubiee init .
scubiee connect --cursor
scubiee stop -y
scubiee init .          # expect BLOCK
scubiee resume
scubiee wipe .          # expect stop→wipe→restart
scubiee wipe --all --confirm --keep-package
scubiee setup --repair
```
