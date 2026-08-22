# Mac & Linux

Install and GPU behavior on macOS and Linux.

---

## Install

```bash
uv tool install scubiee==0.2.54 --index-url https://pypi.org/simple
uv tool update-shell
scubiee setup --repair
cd ~/your/project
scubiee init . --fast
```

**pip alternative:**

```bash
pip install -U scubiee==0.2.54
scubiee setup --repair
```

---

## GPU profiles

| Platform | Default profile | Backend |
|----------|-----------------|---------|
| **Apple Silicon** | `mlx` | MLX Metal FP16 CodeRank |
| **Intel Mac** | `coreml` or `cpu` | CoreML when viable; CPU fallback |
| **Linux + NVIDIA** | `cuda` | ONNX Runtime CUDA |
| **Linux AMD / no GPU** | `cpu` | ONNX Runtime CPU |

Check:

```bash
scubiee setup --status
```

Force a profile:

```bash
scubiee setup --profile mlx --repair    # Apple Silicon
scubiee setup --profile cuda --repair   # Linux NVIDIA
scubiee setup --profile cpu --repair
```

Disable MLX on Mac:

```bash
export CTX_MLX=0
scubiee setup --profile cpu --repair
```

---

## Mac MCP notes

- MCP must use the **venv Python**, not a Homebrew symlink that drops site-packages. `scubiee setup --repair` rewrites `~/.cursor/mcp.json`.
- MLX models require embed work on the correct thread; daemon sync is the real-world path — test with MCP `sync_index`, not only CLI sync.

---

## Linux notes

- No DirectML on Linux — AMD GPUs use CPU embed unless you configure CUDA-capable hardware with NVIDIA.
- Ensure `~/.local/bin` is on PATH for uv tool shims.

---

## Data paths

Same as other platforms:

- `~/.context-engine/` — state, indexes, accel.json
- `~/.cursor/mcp.json` — Cursor MCP config
- `<repo>/.context-engine/id.json` — project identity

Model cache: `~/.cache/fastembed/` (Linux/macOS).

---

## Uninstall

See [Uninstall (Mac/Linux)](./uninstall-mac-linux.md).

---

## Related

- [Getting started](./getting-started.md)
- [Troubleshooting](./troubleshooting.md)
- [Cursor & MCP](./cursor-mcp.md)
