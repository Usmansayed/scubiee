# Uninstall on Windows (uv tool install)

## Why `uv tool uninstall scubiee` fails with Access denied

`uv tool uninstall` deletes the **whole tool environment**, including `Scripts\python.exe`.

While **Cursor MCP** (or the engine daemon) is running, that Python process holds files open. Windows will not delete locked executables — you get:

```text
error: failed to remove directory ...\scubiee\Scripts: Access is denied
```

**pip uninstall** can *look* easier because it only removes the `scubiee` package from site-packages, not the interpreter MCP is using. That is not a full uninstall of a uv tool install.

## Correct flow (one story, no extra commands)

Use **`stop`** then **`wipe`** — same tools you already have:

```powershell
scubiee stop
scubiee wipe --all --yes --package
```

What that does:

1. **`scubiee stop`** — stops watchdog, engine daemon, and processes under `%APPDATA%\uv\tools\scubiee` (MCP / ctx-mcp).
2. **`scubiee wipe --all --yes --package`** — removes indexes, MCP wiring, model caches (optional), and uninstalls scubiee (uv tool or pip).

Then **reload Cursor** (or quit fully) so MCP does not respawn `ctx-mcp`.

If a tool folder remains:

```powershell
uv tool uninstall scubiee
```

Reinstall:

```powershell
uv tool install --force scubiee --index-url https://pypi.org/simple
scubiee setup --repair
```

## If `scubiee` will not start (`pyvenv.cfg` missing)

The tool env is already broken. Quit Cursor, then:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1
```

Or nuclear cleanup without scubiee running:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
```

## Rule of thumb

| Step | Command |
|------|---------|
| Release file locks | `scubiee stop` (+ quit Cursor if stop reports remaining processes) |
| Clean machine + remove package | `scubiee wipe --all --yes --package` |
| Remove leftover uv tool dir | `uv tool uninstall scubiee` |
| Fresh install | `uv tool install scubiee --index-url https://pypi.org/simple` → `scubiee setup` |

Do **not** run raw `uv tool uninstall` while MCP is active.

## faiss `class_wrappers` import error

**Symptom:** `scubiee --version` or any command crashes with `cannot import name 'class_wrappers' from faiss`.

**Cause:** On Windows, `uv tool install` sometimes extracts an **incomplete** `faiss-cpu` wheel (missing `class_wrappers.py`). The wheel on PyPI is fine; the local extract is broken.

**Fix (one command block):**

```powershell
pip download faiss-cpu==1.15.0 -d $env:TEMP\faiss_whl --no-deps
uv pip install --force-reinstall "$env:TEMP\faiss_whl\faiss_cpu-*.whl" --python "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe"
scubiee --version
```

Or run `scripts/repair-uv-scubiee.ps1` (reinstall + faiss fix).

**0.2.45+:** `scubiee` auto-repairs faiss on startup; `scubiee --version` works even before repair.

Also available: `scubiee engine stop` (daemon only). Prefer top-level **`scubiee stop`** before wipe — it includes uv-tool MCP processes.
