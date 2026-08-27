# Windows guide

Windows-specific install, DirectML vs CPU-only laptops, uv tool locks, and repair.

**Docs assume [scubiee 0.2.87](https://pypi.org/project/scubiee/0.2.87/).** Full playbook: [Install & debug](./install-and-debug.md).

---

## Recommended install

```powershell
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
uv tool update-shell
# open a NEW PowerShell window
scubiee setup --repair
cd C:\path\to\your\repo
scubiee init .
scubiee connect --cursor
```

Always pin `--index-url https://pypi.org/simple` on Windows.

If install hits **Access denied**, run `scubiee unlock-tool` first (see below) — **not** Admin PowerShell.

---

## GPU vs CPU (important)

| Hardware | Expected profile |
|----------|------------------|
| Discrete **NVIDIA** or **AMD** GPU | `dml` (DirectML) |
| Intel UHD / Iris / Arc iGPU only | **`cpu`** |
| AMD laptop “Radeon Graphics” APU (no discrete card) | **`cpu`** |
| No GPU | **`cpu`** |

Current Scubiee **ignores Intel iGPU / AMD APU** for DirectML so setup does not hang.

Verify:

```powershell
scubiee setup --status
scubiee diagnose --no-tests --desktop
```

Force CPU:

```powershell
scubiee setup --profile cpu --repair
```

Escape hatch if a rare **discrete** AMD chip was misclassified:

```powershell
scubiee setup --profile dml --repair
```

---

## Access denied on upgrade or reinstall

**Symptom:** `uv tool install --force` cannot overwrite `Scripts\*.exe`; CLI later fails with `No module named 'pipeline'`.

**Cause:** Supervisor / daemon / Cursor MCP locking `%APPDATA%\uv\tools\scubiee`. These are **file locks**, not ACLs. Admin does **not** help. Reboot only works because it kills the locker — use unlock instead.

**Recovery (preferred):**

```powershell
scubiee unlock-tool
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor
```

`unlock-tool` turns MCP off (so Cursor cannot respawn), stops lockers, and frees the tool directory (rename-aside when needed).

**If `scubiee` itself is broken:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
```

Or: `scripts/repair-uv-scubiee.ps1 0.2.87`.

Prefer `scubiee upgrade` when the CLI still works — it unlocks before swapping the package.

After any half-broken reinstall: **`setup --repair` before `init`**.

---

## uv tool layout

| Path | Role |
|------|------|
| `%APPDATA%\uv\tools\scubiee\` | Tool virtualenv |
| `%APPDATA%\uv\tools\scubiee\Scripts\python.exe` | Python used by MCP |
| `%APPDATA%\uv\tools\scubiee\Scripts\scubiee.exe` | CLI entry |
| `%USERPROFILE%\.local\bin\scubiee.exe` | uv shim (PATH) |
| `%USERPROFILE%\.scubiee\` | Indexes, registry, accel |

---

## Diagnose for non-CS users

```powershell
scubiee diagnose --no-tests --desktop
# Creates: Desktop\scubiee-diagnose.json
```

---

## faiss / broken venv

```powershell
powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1 0.2.87
scubiee setup --repair
```

Nuclear:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
uv tool install --force scubiee==0.2.87 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
```

---

## ORT wheel conflicts (manual purge)

If setup still shows CPU providers only on a machine that should be DML:

```powershell
scubiee unlock-tool
# Quit Cursor if unlock reports remaining locks
$Py = "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe"
uv pip uninstall onnxruntime onnxruntime-gpu onnxruntime-directml --python $Py
uv pip install onnxruntime-directml --python $Py
scubiee setup --repair
```

---

## Indexing tips

```powershell
cd C:\path\to\your\repo
# NOT cd C:\Users\you
scubiee init .
scubiee init . --fast --roots packages   # large monorepo
```

---

## Connect tips

```powershell
scubiee connect --cursor
# Special-4: run inside each project
scubiee connect --copilot
scubiee connect --cline
```

Cursor writes **project** `.cursor/mcp.json` with an absolute pin (required — global `${workspaceFolder}` is not expanded).

---

## Uninstall

See [Uninstall on Windows](./uninstall-windows.md).

---

## Related

- [Install & debug](./install-and-debug.md)
- [Getting started](./getting-started.md)
- [Troubleshooting](./troubleshooting.md)
- [Cursor & MCP](./cursor-mcp.md)
