# Product vision

## One sentence

Give coding agents **local, GPU-backed, token-cheap locate** so they find the right span without dumping the repo through Grep and full-file reads.

## What we are building

**Scubiee** (PyPI/npm name) is the installable product. **Context Engine (CE)** is the local daemon + MCP server inside it.

A developer runs `pip install scubiee` → `ctx setup` once per machine → `ctx init <repo>` per codebase. Cursor (or another MCP host) talks to a **stdio MCP** process that forwards to a **localhost HTTP engine** (`127.0.0.1:8765`). That engine keeps a **warm** index: Merkle freshness, tree-sitter graph, compressed CodeRank embeddings, FAISS, BM25, Conductor fusion.

Agents must **not** treat the IDE’s native Grep/Glob/semantic search as the discovery path when CE is healthy. The product is the trajectory, not “another search API.”

## How we try to achieve it

| Pillar | How we implement it | Success look |
|--------|---------------------|--------------|
| **Locate, don’t dump** | Phase MCP: `map` (skinny cards) → `focus` (outline/span/neighbors) → edit. `grep`/`glob` only for a **known** literal/filename. | Agent cites 1–3 files, edits, does not open 40 files |
| **Better than grep for meaning** | Conductor `D_channel_best`: BM25 + dense CodeRank + graph affinity, fused by min-rank + agreement | Natural-language “where does session die” hits the recovery handler |
| **Cheap tokens** | Mix compress (512-char cap) before embed; MCP returns pointers + budgeted spans; session store dedupes already-shown bodies | Same span not re-sent as a full dump |
| **Always local** | No cloud embed required. Model + index on disk under `~/.context-engine/` | Works offline after first model download |
| **Use the machine’s GPU** | Auto profile: CUDA / DirectML / **MLX FP16 (Apple Silicon)** / CoreML (Intel Mac fallback path) / CPU. Embed weights are **FP16 only** (ONNX `model_fp16.onnx` or MLX FP16). | MacBook indexes on Metal, not silent CPU |
| **Stay fresh without full reindex** | Merkle + incremental sync + daemon `/v1/publish` so search generation bumps in the **running** process | Edit a `.py` file, `ctx sync`, search hits it without restart |
| **Install once, forget** | `ctx setup` writes accel profile, MCP json, Cursor rule template, logon supervisor | Second machine: two commands, MCP works |

## What “good” is *not*

- Telling the user to `--profile cpu` because GPU setup is hard.
- Hard-blocking `map` after 4 calls (`thrash_blocked`). Guidance only (`usage_hint`).
- Resolving `sys.executable` on macOS so MCP points at Homebrew Cellar and `import pipeline` dies.
- Mixing native Grep with phase MCP for discovery (breaks the sealed trajectory).
- Putting the full tool table in `.cursor/rules` (tokens). Trajectory lives in **MCP server instructions**.

## Surfaces (agent-facing)

Default after setup: `CTX_MCP_SURFACE=phase`.

| Tool | Job |
|------|-----|
| `map` | Cold / meaning locate — cards, no bodies |
| `focus` | Deepen one target: outline, span, neighbors |
| `grep` | Known exact string only |
| `glob` | Known filename/path only |
| `workspace` | Pins / heatmap / already focused |
| `status` | Health only — never locate |

Other surfaces (`read`, `nav`, `search`, …) still exist for experiments; **phase is the product**.

## Hardware vision (Mac vs Windows)

- **Apple Silicon:** MLX runs CodeRank on Metal (`packages/pipeline/mlx_mac.py`). Weights converted from CodeRank ONNX. Default FP16. GPU stream is **per-thread** (MLX ≥0.31).
- **Windows NVIDIA:** `onnxruntime-gpu` + CUDA EP.
- **Windows AMD/Intel:** DirectML.
- **CoreML:** kept as an ORT path (static-shape CodeRank) but **not** the Mac production default after 0.2.11; CoreML crashed on dynamic shapes and invalid EP options.

## Packaging vision

- **PyPI `scubiee`:** source of truth for `ctx` / `ctx-mcp`. Darwin wheels pull FastEmbed, ORT, ONNX, MLX without extras.
- **npm `scubiee`:** wrapper that creates a venv and pip-installs. **Not published yet** (registry 404; needs `NPM_TOKEN`).
- User Mac venv is **`~/scubiee`**, not `~/.context-engine/venv`. Runtime files still live in `~/.context-engine/`.

## North-star user loop

```text
pip install -U scubiee==0.2.13
source ~/scubiee/bin/activate    # this user's Mac
ctx setup --repair
ctx init /path/to/repo
# Cursor: reload MCP
# Agent: map → focus(span) → native Read cited lines → Edit
```
