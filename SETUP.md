# Context Engine — Setup Guide

Everything a new team member needs to go from a fresh clone to a working system.

## Prerequisites

- Python 3.10+ (3.11 or 3.12 recommended)
- Git
- 8GB+ RAM (16GB recommended for indexing large repos)
- Optional: NVIDIA GPU with CUDA toolkit, or AMD/Intel GPU on Windows (DirectML)

## 1. Clone the repo

```bash
git clone https://github.com/Usmansayed/new-context-engine.git
cd new-context-engine
```

## 2. Create virtual environment

```bash
# Linux / macOS
python -m venv .venv
source .venv/bin/activate

# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## 3. Install base dependencies

```bash
pip install -e .
```

This installs all core packages (numpy, faiss-cpu, tree-sitter grammars, networkx, etc.) plus the `ctx` and `ctx-mcp` CLI commands.

## 4. Install MCP support

```bash
pip install "mcp>=1.0,<2"
```

Or:

```bash
pip install -e ".[mcp]"
```

## 5. Install acceleration (GPU or CPU)

The embedding model (CodeRankEmbed) runs on ONNX Runtime. You need to install the right wheel for your hardware.

### Option A: Automatic detection (recommended)

```bash
ctx init
```

This will:
1. Detect your hardware (NVIDIA, AMD/Intel on Windows, or CPU-only)
2. Install the correct ONNX Runtime wheel
3. Install FastEmbed
4. Download the CodeRankEmbed ONNX model (~100MB, from HuggingFace)
5. Run a microbenchmark to verify performance

### Option B: Force a specific profile

```bash
# NVIDIA GPU (requires CUDA toolkit installed)
ctx init --profile cuda

# AMD/Intel GPU on Windows (DirectML — no CUDA needed)
ctx init --profile dml

# CPU only (any OS, no GPU)
ctx init --profile cpu
```

### Option C: Manual install (if ctx init fails)

Pick ONE set of commands based on your hardware:

**NVIDIA (CUDA):**
```bash
pip install fastembed>=0.4 huggingface_hub>=0.20
pip uninstall -y onnxruntime onnxruntime-directml
pip install onnxruntime-gpu>=1.17
```

**AMD/Intel on Windows (DirectML):**
```bash
pip install fastembed>=0.4 huggingface_hub>=0.20
pip uninstall -y onnxruntime onnxruntime-gpu
pip install onnxruntime-directml>=1.17
```

**CPU only (any OS):**
```bash
pip install fastembed>=0.4 huggingface_hub>=0.20
pip install onnxruntime>=1.17
```

### Option D: SentenceTransformers backend (alternative, heavier)

If ONNX/FastEmbed doesn't work on your system:

```bash
pip install -e ".[embed-st]"
```

This installs PyTorch + SentenceTransformers. Set `CTX_EMBED_BACKEND=coderank` in your environment.

## 6. Download the embedding model

The model is `nomic-ai/CodeRankEmbed` (ONNX export at `jamie8johnson/CodeRankEmbed-onnx`).

If `ctx init` succeeded, the model is already downloaded and cached by FastEmbed (usually at `~/.cache/fastembed/` or `~/.cache/huggingface/`).

If you need to download it manually:

```bash
python -c "from fastembed import TextEmbedding; TextEmbedding('nomic-ai/CodeRankEmbed')"
```

This downloads ~100MB from HuggingFace on first run. Subsequent runs use the cache.

## 7. Get the test data

The `testdata/` directory is gitignored because it contains test repositories that can be large. You need to set it up:

### frontend-mcp (primary test corpus)

Ask a team member for the `testdata/frontend-mcp/` directory, or clone from the internal repo if one exists. This is a synthetic frontend MCP project (~3000 source files) used by all experiments.

If you have access to the original source:
```bash
# Copy or symlink into testdata/
mkdir testdata
cp -r /path/to/frontend-mcp testdata/frontend-mcp
```

### Other test repos (optional)

- `testdata/scubiee-news-flow` — used by the `@slow` pytest marker
- `testdata/graphify` — Graphify extraction test data
- `testdata/cursor_sdk_ab` — Cursor SDK trial artifacts

## 8. Environment variables

Copy the example and fill in what you need:

```bash
cp .env.example .env
```

**Required for experiments (not for local search):**
- `GOOGLE_GENERATIVE_AI_API_KEY` or `GEMINI_API_KEY` — for OpenCode A/B tests with Gemini
- `AWS_BEARER_TOKEN_BEDROCK` — for Bedrock/Nova experiments

**For local-only usage, no API keys are needed.** The engine runs entirely locally.

## 9. First run — index a repo

```bash
# Full setup: detect hardware + start daemon + register Cursor MCP
ctx setup --repo /path/to/your/project

# Or step by step:
ctx init                                    # hardware detection
ctx engine start /path/to/your/project      # start daemon
ctx index /path/to/your/project             # index the repo
ctx search "where is authentication" /path/to/your/project  # test it
```

## 10. Verify everything works

```bash
# Check engine health
ctx engine status

# Run the test suite (no testdata needed for most unit tests)
pytest tests/ -x -q

# Quick search test
ctx search "how does session handling work" .
```

## 11. IDE integration (Cursor / Kiro / OpenCode)

### Cursor

`ctx setup` writes `.cursor/mcp.json` automatically. Just reload MCP in Cursor (Settings → MCP → refresh).

### Kiro

Add to `.kiro/settings/mcp.json`:
```json
{
  "mcpServers": {
    "context-engine": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-u", "-m", "pipeline.mcp_locate"],
      "env": {
        "PYTHONPATH": "/path/to/context-engine/packages",
        "CTX_REPO": "/path/to/target/repo",
        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
        "CTX_TOKEN_MODE": "savings",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

### OpenCode

Add to `opencode.json` in your project:
```json
{
  "mcp": {
    "context-engine": {
      "type": "local",
      "enabled": true,
      "command": ["/path/to/.venv/bin/python", "-m", "pipeline.mcp_locate"],
      "environment": {
        "PYTHONPATH": "/path/to/context-engine/packages",
        "CTX_REPO": "/path/to/target/repo",
        "CTX_ENGINE_URL": "http://127.0.0.1:8765"
      },
      "timeout": 120000
    }
  }
}
```

## 12. Running experiments

The A/B testing harnesses need:
1. The engine daemon running with the test corpus indexed
2. OpenCode CLI installed (`npm install -g opencode-ai`)
3. An API key for the model provider

```bash
# Start daemon on test corpus
ctx engine start testdata/frontend-mcp

# Run raw vs ce_search A/B
.\.venv\Scripts\python.exe -u scripts\experiments\opencode_raw_vs_ce\run.py

# Dry run (validate without API calls)
.\.venv\Scripts\python.exe -u scripts\experiments\opencode_raw_vs_ce\run.py --dry-run
```

## Troubleshooting

### "No index found" error
Run `ctx index .` or `ctx register .` on the target repo first.

### Engine won't start / port in use
```bash
ctx engine stop          # kill existing
ctx engine start .       # start fresh
```

### ORT provider errors (DML/CUDA not found)
Re-run `ctx init --profile cpu` to fall back to CPU. Or check that only ONE onnxruntime wheel is installed:
```bash
pip list | grep onnxruntime
# Should show exactly ONE of: onnxruntime, onnxruntime-gpu, onnxruntime-directml
```

### psutil missing (resource manager warnings)
```bash
pip install psutil
```

### Embedding is slow
- Check `ctx init --status` to see your accel profile
- DML on Windows: batch_size=16 is safe for most GPUs
- CUDA: batch_size=32-64 depending on VRAM
- CPU: batch_size=8-16, expect ~2-5 texts/sec

### Tests fail with import errors
Make sure you're running from the repo root with the venv active:
```bash
pytest tests/ -x
```

The `pytest.ini` sets `pythonpath = packages` so all packages are importable.

## File locations summary

| What | Where | Gitignored? |
|------|-------|-------------|
| Source packages | `packages/` | No |
| Accel profile | `~/.context-engine/accel.json` | N/A (home dir) |
| Hardware snapshot | `~/.context-engine/hardware.json` | N/A |
| Engine daemon files | `~/.context-engine/engine.*` | N/A |
| Vector indexes | `~/.context-engine/vectordb/` | N/A |
| Project index data | `~/.context-engine/projects/ce_*/` | N/A |
| Embedding model cache | `~/.cache/fastembed/` or `~/.cache/huggingface/` | N/A |
| Test repositories | `testdata/` | Yes |
| Experiment outputs | `out/` | Yes |
| Session state | `<repo>/.context-engine/` | Yes |
| Research data | `research/` | Yes |
| Local secrets | `.env` | Yes |

## What's NOT in the git repo (and why)

| Item | Reason | How to get it |
|------|--------|---------------|
| Embedding model (~100MB) | Too large for git | `ctx init` downloads it from HuggingFace |
| Vector indexes | Regenerated per-machine | `ctx index <repo>` rebuilds them |
| `testdata/` repos | Large, some proprietary | Ask team / clone internal repos |
| `research/` data | Large (DuckDB, traces) | Ask team for research artifacts |
| `.context-engine/` state | Machine-specific | Regenerated on first `ctx setup` |
| `out/` experiment results | Generated per-run | Re-run experiments to regenerate |
| `.env` secrets | Security | Copy `.env.example`, fill in your keys |
