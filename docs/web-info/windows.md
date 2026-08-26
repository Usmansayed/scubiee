# Windows guide

Windows-specific install, DirectML vs CPU-only laptops, uv tool locks, and repair.

**Docs assume scubiee 0.2.82.**

---

## Recommended install

```powershell
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple --refresh
uv tool update-shell
# open a NEW PowerShell window
scubiee setup --repair
cd C:\path\to\your\repo
scubiee init .
scubiee connect --cursor
```

Always pin `--index-url https://pypi.org/simple` on Windows.

---

## GPU vs CPU (important)

| Hardware | Expected profile |
|----------|------------------|
| Discrete **NVIDIA** or **AMD** GPU | `dml` (DirectML) |
| Intel UHD / Iris / Arc iGPU only | **`cpu`** |
| AMD laptop “Radeon Graphics” APU (no discrete card) | **`cpu`** |
| No GPU | **`cpu`** |

Current Scubiee **ignores Intel iGPU / AMD APU** for DirectML so setup does not hang. Friend-laptop validation: Intel i5-1235U → **`cpu`**, setup completes (~2–3 t/s typical).

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

**Cause:** Supervisor / daemon / Cursor MCP locking `%APPDATA%\uv\tools\scubiee`.

**Recovery:**

```powershell
scubiee stop
# Task Manager → end "ContextEngineSupervisor" if needed
# Quit Cursor completely
Remove-Item -Recurse -Force "$env:APPDATA\uv\tools\scubiee" -ErrorAction SilentlyContinue
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
```

Prefer `scubiee upgrade` when possible — it stops CE processes before swapping the package.

After any half-broken reinstall: **`setup --repair` before `init`** (stale `accel.json` can look fine while FastEmbed is missing).

---

## uv tool layout

| Path | Role |
|------|------|
| `%APPDATA%\uv\tools\scubiee\` | Tool virtualenv |
| `%APPDATA%\uv\tools\scubiee\Scripts\python.exe` | Python used by MCP |
| `%APPDATA%\uv\tools\scubiee\Scripts\scubiee.exe` | CLI entry |
| `%USERPROFILE%\.local\bin\scubiee.exe` | uv shim (PATH) |
| `%USERPROFILE%\.context-engine\` | Indexes, registry, accel |

---

## Diagnose for non-CS users

```powershell
scubiee diagnose --no-tests --desktop
# Creates: Desktop\scubiee-diagnose.json
```

`$env:USERPROFILE\…` paths in `--output` are expanded; `--desktop` is the simplest share path.

---

## faiss / broken venv

See [Troubleshooting](./troubleshooting.md) or:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1 0.2.82
scubiee setup --repair
```

Nuclear:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple
scubiee setup --repair
```

---

## ORT wheel conflicts (manual purge)

If setup still shows CPU providers only on a machine that should be DML:

```powershell
scubiee stop
# Quit Cursor
$Py = "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe"
uv pip uninstall onnxruntime onnxruntime-gpu onnxruntime-directml --python $Py
# Delete leftover folder if needed:
# %APPDATA%\uv\tools\scubiee\Lib\site-packages\onnxruntime
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

---

## Uninstall

See [Uninstall on Windows](./uninstall-windows.md).

---

## Related

- [Getting started](./getting-started.md)
- [Troubleshooting](./troubleshooting.md)
- [Cursor & MCP](./cursor-mcp.md)
