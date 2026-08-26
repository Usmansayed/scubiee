# Mac & Linux

Install and GPU behavior on macOS and Linux.

**Docs assume scubiee 0.2.82.**

---

## Install

```bash
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple
uv tool update-shell
# new terminal
scubiee setup --repair
cd ~/your/project
scubiee init .
scubiee connect --cursor    # or --kiro / --copilot / … inside each Special-4 project
```

**pip alternative:**

```bash
pip install -U scubiee==0.2.82
scubiee setup --repair
```

---

## GPU profiles

| Platform | Default profile | Backend |
|----------|-----------------|---------|
| **Apple Silicon** | `mlx` | MLX Metal FP16 CodeRank |
| **Intel Mac** | `coreml` or `cpu` | CoreML when viable; CPU otherwise |
| **Linux + NVIDIA** | `cuda` | ONNX Runtime CUDA |
| **Linux AMD / no GPU** | `cpu` | ONNX Runtime CPU |

Check:

```bash
scubiee setup --status
scubiee diagnose --no-tests --desktop
```

### Apple Silicon must not stay on CPU

After `setup --repair`, profile should be **`mlx`**. If you forced CPU for debugging:

```bash
scubiee setup --repair
# or explicitly:
scubiee setup --profile mlx --repair
```

Disable MLX only if you intend CPU:

```bash
export CTX_MLX=0
scubiee setup --profile cpu --repair
```

Force other profiles:

```bash
scubiee setup --profile cuda --repair   # Linux NVIDIA
scubiee setup --profile cpu --repair
```

---

## Mac MCP notes

- MCP must use the **venv / uv tool Python**, not a Homebrew symlink that drops site-packages. `scubiee connect --cursor` or `setup --repair` rewrites `~/.cursor/mcp.json`.
- After `init`, always **`connect`** so the agent rule is present.
- Pause/stop → **`scubiee resume`** (not `wake`).

---

## Linux notes

- No DirectML on Linux — AMD GPUs use CPU embed unless you have NVIDIA + CUDA.
- Ensure `~/.local/bin` is on PATH for uv tool shims.

---

## Data paths

- `~/.context-engine/` — state, indexes, `accel.json`
- `~/.cursor/mcp.json` — Cursor MCP (from **connect**)
- `<repo>/.context-engine/id.json` — project identity

Model cache: `~/.cache/fastembed/` (and MLX-related caches as configured).

---

## Uninstall

See [Uninstall (Mac/Linux)](./uninstall-mac-linux.md).

---

## Related

- [Getting started](./getting-started.md)
- [Troubleshooting](./troubleshooting.md)
- [Cursor & MCP](./cursor-mcp.md)
- Mac verification checklist (maintainers): [`../macos-deferred-verification.md`](../macos-deferred-verification.md)
