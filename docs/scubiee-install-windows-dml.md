# Installing Scubiee on Windows (DirectML GPU)

## TL;DR

```powershell
# One-time install — the --overrides flag keeps GPU acceleration from breaking.
uv tool install --overrides packaging/uv-overrides-win-dml.txt scubiee
scubiee setup
scubiee init .
```

`uv` records the override in the tool receipt, so later `uv tool upgrade scubiee`
keeps it automatically. You only pass `--overrides` on the first install.

## Why the override is needed

`fastembed` (Scubiee's embedding backend) declares an **unbounded** dependency on
the generic `onnxruntime` package. On Windows, Scubiee wants
`onnxruntime-directml` instead — it provides the same `onnxruntime` **import
package** plus the `DmlExecutionProvider` that runs embeddings on the GPU.

The two wheels install into the **same `onnxruntime/` folder** and overwrite each
other's native DLLs (pip/uv don't flag this — the package *names* differ, so
`pip check` passes). When the generic wheel's DLLs win, `DmlExecutionProvider`
silently disappears and embedding falls back to CPU — much slower, with no error.
This is the same class of clash as `opencv-python` vs `opencv-contrib-python`
(see astral-sh/uv#9073).

The override tells uv's resolver to drop the generic `onnxruntime` from the whole
dependency tree:

```
onnxruntime; sys_platform == 'never'
```

`sys_platform == 'never'` is false on every platform, so the generic wheel is
excluded from resolution entirely. Only `onnxruntime-directml` (pulled by
Scubiee's own `win32` dependency) is installed, so the DLL clobber can't happen.

## If GPU acceleration is already broken

If you installed without the override and the engine logs
`GPU acceleration is OFF … Run scubiee setup --repair`:

```powershell
scubiee setup --repair
```

`setup --repair` reconciles the ORT wheels (uninstall-all → reinstall
`onnxruntime-directml`) with no engine running — the safe way to fix it. To
prevent it recurring, reinstall once with the override:

```powershell
scubiee stop
uv tool install --force --reinstall --overrides packaging/uv-overrides-win-dml.txt scubiee
```

## Notes
- **Windows/DML only.** Linux (plain `onnxruntime` or `onnxruntime-gpu`) and macOS
  (plain `onnxruntime` for CoreML/MLX) must NOT use this override.
- The running engine never repairs ORT itself (running pip against its own live
  site-packages can corrupt the install); it only detects the broken state and
  points you at `setup --repair`.
- Verify GPU is active: `scubiee setup --repair` ends with `Ready (dml)`, and the
  engine log shows `providers=('DmlExecutionProvider', …)` / `[embed] … device=dml`.
