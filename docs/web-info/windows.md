# Windows guide

Windows-specific install, DirectML (AMD/Intel GPU), uv tool layout, and repair scripts.

---

## Recommended install

```powershell
uv cache clean scubiee
uv tool install --force scubiee==0.2.50 --index-url https://pypi.org/simple --refresh
uv tool update-shell
# restart terminal
scubiee setup --repair
```

Always pin `--index-url https://pypi.org/simple` on Windows to avoid stale uv cache serving old or partial wheels.

---

## DirectML (AMD / Intel GPU)

Scubiee auto-selects **`dml`** profile on Windows when a suitable GPU is present:

- Installs `onnxruntime-directml`
- Uses `DmlExecutionProvider` for CodeRank FP16 embed
- Saves calibrated batch in `~/.context-engine/accel.json`

Verify:

```powershell
scubiee setup --status
scubiee preflight .
```

You should see `"profile": "dml"` and `"provider": "DmlExecutionProvider"`.

Force CPU if debugging:

```powershell
scubiee setup --profile cpu --repair
```

---

## uv tool layout

| Path | Role |
|------|------|
| `%APPDATA%\uv\tools\scubiee\` | Tool virtualenv |
| `%APPDATA%\uv\tools\scubiee\Scripts\python.exe` | Python used by MCP |
| `%APPDATA%\uv\tools\scubiee\Scripts\scubiee.exe` | CLI entry |
| `%USERPROFILE%\.local\bin\scubiee.exe` | uv shim (add to PATH) |
| `%USERPROFILE%\.context-engine\` | Indexes, registry, accel |

---

## faiss `class_wrappers` error

Common after `uv tool install`. See [Troubleshooting](./troubleshooting.md#faiss-cannot-import-name-class_wrappers) or run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1 0.2.50
scubiee setup --repair
```

---

## Broken venv / pyvenv.cfg missing

1. **Quit Cursor completely** (MCP holds file locks)
2. Run repair script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1 0.2.50
scubiee setup --repair
```

Nuclear option:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
uv tool install --force scubiee==0.2.50 --index-url https://pypi.org/simple
scubiee setup --repair
```

---

## ORT wheel conflicts (manual purge)

If `scubiee setup --repair` still shows CPU providers only:

1. Quit Cursor and `scubiee stop`
2. Using the **uv tool Python**:

```powershell
$Py = "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe"
uv pip uninstall onnxruntime onnxruntime-gpu onnxruntime-directml --python $Py
# manually delete leftover folder if present:
# %APPDATA%\uv\tools\scubiee\Lib\site-packages\onnxruntime
uv pip install onnxruntime-directml --python $Py
scubiee setup --repair
```

---

## Indexing tips on Windows

```powershell
cd C:\path\to\your\repo
# NOT cd C:\Users\you
scubiee init . --fast
scubiee init . --fast --roots packages   # large monorepo
```

Home directory block is intentional — see [Indexing & projects](./indexing-and-projects.md).

---

## Uninstall

Full guide: [Uninstall on Windows](./uninstall-windows.md)

Short version:

```powershell
scubiee stop
scubiee wipe --all --yes --package
# quit Cursor, reload
uv tool uninstall scubiee   # if folder remains
```

---

## Related

- [Getting started](./getting-started.md)
- [Troubleshooting](./troubleshooting.md)
- [Uninstall on Windows](./uninstall-windows.md)
