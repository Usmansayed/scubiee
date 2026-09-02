# Uninstall on Windows (uv tool install)

Complete guide for removing Scubiee on Windows when MCP, the engine daemon, or uv file locks get in the way.

**Docs assume [scubiee 0.3.13](https://pypi.org/project/scubiee/0.3.13/).** See also [Install & debug](./install-and-debug.md).

---

## Why `uv tool uninstall scubiee` fails with Access denied

`uv tool uninstall` deletes the **whole tool environment**, including `Scripts\python.exe`.

While **Cursor MCP** (or the engine daemon) is running, that Python process holds files open. Windows will not delete locked executables:

```text
error: failed to remove directory ...\scubiee\Scripts: Access is denied
```

This is a **file lock**, not an ACL problem. **Admin PowerShell does not help.** Reboot “works” only because it kills the locker — use unlock instead.

**pip uninstall** can *look* easier because it only removes the `scubiee` package from site-packages, not the interpreter MCP is using. That is **not** a full uninstall of a uv tool install.

---

## Correct flow (recommended)

```powershell
scubiee unlock-tool          # MCP-off → stop lockers → free tool dir
scubiee wipe --all --confirm --package
```

Or if you only need to free locks for reinstall:

```powershell
scubiee unlock-tool
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
```

What **`unlock-tool`** does:

1. Disables `scubiee` in global + project MCP (so Cursor cannot respawn)
2. Stops daemon / watchdog / uv-tool processes (without killing itself mid-run)
3. Frees `%APPDATA%\uv\tools\scubiee` (rename-aside + retries when needed)

What **`wipe --all --confirm --package`** does:

1. Removes indexes, MCP wiring, model caches, rules, enrolled markers
2. Uninstalls scubiee — JSON **`audit.remaining`** lists paths still on disk if locks remain

Then **reload Cursor** so MCP picks up the new state.

Fresh install:

```powershell
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor
```

### Upgrade / reinstall also hits Access denied

```powershell
scubiee unlock-tool
# or: scubiee upgrade   (unlocks before package swap when possible)
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor
```

---

## Wipe flags (reference)

| Flag | Meaning |
|------|---------|
| `--all` | Machine-wide Scubiee state (required target for full uninstall) |
| `--yes` or `--confirm` | Confirm destructive wipe (required with `--all`) |
| `--package` | Uninstall scubiee package (default with `--all --confirm`) |
| `--keep-package` | Wipe state but keep uv tool |
| `--keep-models` | Keep CodeRank / FastEmbed cache downloads |

Repo-only wipe (one project):

```powershell
cd C:\path\to\repo
scubiee wipe .
# or
scubiee remove . --delete-store
```

---

## If `scubiee` will not start (`pyvenv.cfg` missing / no `pipeline`)

The tool env is already broken. Prefer the standalone scripts (they disable MCP **before** killing processes):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1 0.3.13
scubiee setup --repair
```

Or nuclear cleanup without scubiee running:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor
```

---

## Rule of thumb

| Step | Command |
|------|---------|
| Free Windows locks | `scubiee unlock-tool` |
| Clean machine + remove package | `scubiee wipe --all --confirm --package` |
| CLI already broken | `scripts/uninstall-uv-scubiee.ps1` or `repair-uv-scubiee.ps1 0.3.13` |
| Fresh install | `uv tool install scubiee==0.3.13 …` → `setup --repair` → `connect` |

Do **not** run raw `uv tool uninstall` / `Remove-Item` on the tool dir while MCP is active (partial delete → `No module named 'pipeline'`).

---

## faiss `class_wrappers` import error

**Symptom:** `scubiee --version` crashes with `cannot import name 'class_wrappers' from faiss`.

**Cause:** Incomplete `faiss-cpu` extract under the uv tool env.

**Fix:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1 0.3.13
scubiee --version
```

Or:

```powershell
pip download faiss-cpu==1.15.0 -d $env:TEMP\faiss_whl --no-deps
uv pip install --force-reinstall "$env:TEMP\faiss_whl\faiss_cpu-*.whl" --python "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe"
```

---

## Stale home registration after experiments

```powershell
scubiee remove C:\Users\YourName --delete-store
Remove-Item C:\Users\YourName\.scubiee\id.json -Force -ErrorAction SilentlyContinue
```

See [Indexing & projects](./indexing-and-projects.md) and [Troubleshooting](./troubleshooting.md).

---

## Related

- [Install & debug](./install-and-debug.md)
- [Windows guide](./windows.md)
- [Troubleshooting](./troubleshooting.md)
- [Uninstall (Mac/Linux)](./uninstall-mac-linux.md)
