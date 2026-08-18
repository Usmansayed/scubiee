# Mac GPU Install Handoff — Context for Cursor on MacBook

> **Purpose:** Pull this repo on Apple Silicon Mac, read this file first, then fix/verify CoreML GPU path for `scubiee` / Context Engine.
>
> **Repos:**
> - Public: `https://github.com/Usmansayed/new-context-engine.git`
> - Hidden handoff: `https://github.com/Usmansayed/hidden-context-engine-.git`
> - Branch: `feat/production-certification` (as of 2026-08-19)

---

## TL;DR — What is broken

**User goal:** Install `scubiee` on MacBook Air (Apple Silicon, Python 3.12 venv) and run embeddings on **GPU (Metal via CoreML)**, not CPU.

**Current failure (scubiee 0.2.7 on PyPI):** `ctx setup --repair` **appears to succeed** but silently runs on **CPU** because CoreML EP rejects invalid provider options.

**Exact error on Mac (0.2.7):**

```
EP Error ... Unknown option: UseCPUAndGPU
 when using [('CoreMLExecutionProvider', {
   'ModelFormat': 'MLProgram',
   'MLComputeUnits': 'CPUAndGPU',
   'RequireStaticInputShapes': '1',
   'EnableOnSubgraphs': '0',
   'UseCPUAndGPU': '1',
   'CreateMLProgram': '1'
 })]
Falling back to ['CPUExecutionProvider'] and retrying.
```

**Root cause in code:** `packages/pipeline/coreml_mac.py` → `coreml_provider_options()` passes two options that are **NOT** valid ONNX Runtime string provider options:

| Bad option | Why wrong |
|------------|-----------|
| `UseCPUAndGPU` | C-API flag (`COREML_FLAG_USE_CPU_AND_GPU`), not a provider option string |
| `CreateMLProgram` | Redundant/wrong; use `ModelFormat=MLProgram` instead |

Valid ORT CoreML options (see [ORT CoreML EP docs](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html)): `MLComputeUnits`, `ModelFormat`, `RequireStaticInputShapes`, `EnableOnSubgraphs`, etc.

**Second bug (same file):** `prepare_coderank_onnx_for_coreml()` called `make_input_shape_fixed(..., shape)` but `shape` was **undefined**. Exception swallowed → static ONNX patch silently fails → dynamic model may still be used.

**Fix applied on branch (0.2.8):**

1. Remove `UseCPUAndGPU` and `CreateMLProgram` from `coreml_provider_options()`.
2. Set `shape = [batch, seq]` before patching ONNX inputs.

---

## Full conversation arc (Windows dev → Mac trial)

### Phase 1 — Reliability & publish (0.2.5 → 0.2.6)

Work on `feat/production-certification` / merged to `main`:

- Search CLI: workspace path to `/v1/search`, fail-fast when engine down
- Path pollution fixes, MCP/daemon health-first, live reindex + FAISS id mapping
- Doctor exit 0 when index OK but daemon unbound; init `--fast` / `--roots`
- Mac npm installer venv + git pip fallback
- **PyPI 0.2.6 published** manually; tags `v0.2.5`, `v0.2.6`
- **npm `scubiee` NOT published** (404 — needs NPM_TOKEN)

### Phase 2 — Mac user install journey

Environment: MacBook Air, Apple Silicon, Python 3.12, venv at `~/.context-engine/venv`.

| Step | Result |
|------|--------|
| `pip install scubiee` (0.2.6) | OK |
| `ctx setup` | **FAILED** — CoreML EP errors |
| CoreML errors | `E5RT`, dynamic shapes, `runtime shape ({1,6,12,0}) has zero elements` |
| Workaround advised | `ctx setup --profile cpu --repair` — user **rejected** CPU-only path |

### Phase 3 — Mac GPU research & 0.2.7 implementation

**Research conclusion:** Mac has no CUDA. GPU path = **ONNX Runtime CoreML EP** → Metal GPU.

Requirements for transformer ONNX on Apple Silicon:

1. **Static input shapes** (`RequireStaticInputShapes=1`)
2. **Fixed batch size** at runtime (pad batches; never `batch_size=len(batch)` on CoreML)
3. **Patch CodeRank ONNX** from dynamic axes to fixed `[batch, 512]`
4. **`MLComputeUnits=CPUAndGPU`** for Metal GPU (not ANE-only)
5. **GPU-only sessions** via `CTX_MAC_GPU_ONLY=1` (default) — exclude CPU EP from provider list

**New module:** `packages/pipeline/coreml_mac.py`  
**Updated:** `packages/pipeline/accel.py`, `packages/pipeline/embedder.py`  
**Tests:** `tests/test_coreml_mac.py`  
**Published:** scubiee **0.2.7** to PyPI (2026-08-19)

### Phase 4 — 0.2.7 still broken on real Mac (this handoff)

User ran on Mac:

```bash
pip install -U "scubiee[coreml]==0.2.7"
ctx setup --repair
```

Output: model downloaded (~549MB), then **UseCPUAndGPU** error, CPU fallback, calibration `21.58 t/s`, printed `Ready` — **misleading success on CPU**.

User wants GPU-only, bug-free Mac path — not CPU workaround.

---

## Architecture: Mac GPU path in scubiee

```
ctx setup --repair
  └─ accel.configure(profile=coreml)
       ├─ install onnxruntime + onnx (coreml extra)
       ├─ register_coreml_coderank_model()
       │    ├─ snapshot_download CodeRank ONNX
       │    ├─ prepare_coderank_onnx_for_coreml()  ← static [20, 512]
       │    └─ FastEmbed custom model: nomic-ai/CodeRankEmbed-coreml-static
       ├─ calibrate_batch() on CoreML EP
       └─ save ~/.context-engine/accel.json

embedder (runtime)
  └─ static_embed_batch_size() → fixed batch 20
  └─ pad_embed_batch() → pad to 20 rows
  └─ coreml_providers() → CoreML EP only if CTX_MAC_GPU_ONLY=1
```

**Key files:**

| File | Role |
|------|------|
| `packages/pipeline/coreml_mac.py` | CoreML options, ONNX patch, batch padding |
| `packages/pipeline/accel.py` | Profile detect, setup, calibrate, save accel.json |
| `packages/pipeline/embedder.py` | Uses static batch + pad on Darwin/coreml |
| `packages/pipeline/preflight.py` | Validates saved provider can warm model |
| `packages/pipeline/doctor.py` | Diagnostics; hints `setup --repair` |

**Persisted config:** `~/.context-engine/accel.json`  
**Static model marker:** `~/.context-engine/coderank_coreml_static.json`

---

## Environment variables (Mac GPU)

```bash
export CTX_MAC_GPU_ONLY=1          # default: CoreML only, no CPU EP in provider list
export CTX_COREML_UNITS=CPUAndGPU  # Metal GPU (default)
export CTX_COREML_STATIC_BATCH=20  # fixed ORT batch size
export CTX_COREML_STATIC_SEQ=512   # fixed sequence length for ONNX patch
```

Set `CTX_MAC_GPU_ONLY=0` only for debugging CPU fallback.

---

## Commands for Mac verification (after fix)

```bash
# 1. venv
source ~/.context-engine/venv/bin/activate
export PATH="$HOME/.context-engine/venv/bin:$PATH"

# 2. Install from git (this branch) OR PyPI when 0.2.8 published
pip install -U "scubiee[coreml] @ git+https://github.com/Usmansayed/hidden-context-engine-.git@feat/production-certification"
# OR after publish:
# pip install -U "scubiee[coreml]==0.2.8"

# 3. Clean broken accel profile from 0.2.7 CPU fallback
rm -f ~/.context-engine/accel.json

# 4. GPU env
export CTX_MAC_GPU_ONLY=1
export CTX_COREML_UNITS=CPUAndGPU

# 5. Repair setup — MUST NOT show "Unknown option" or "Falling back to CPU"
ctx setup --repair 2>&1 | tee ~/ce-setup.log

# 6. Verify profile
ctx setup --status
python -c "import json; print(json.load(open('$HOME/.context-engine/accel.json')))"
python -c "import onnxruntime as ort; print(ort.get_available_providers())"

# 7. Index + engine
cd /path/to/your/repo
ctx init .
ctx engine ensure .
ctx search "test query"
```

**Success criteria:**

- [ ] No `Unknown option: UseCPUAndGPU` in setup log
- [ ] No `Falling back to ['CPUExecutionProvider']` during calibration
- [ ] `accel.json` has `"profile": "coreml"`, `"provider": "CoreMLExecutionProvider"`
- [ ] `~/.context-engine/coderank_coreml_static.json` exists
- [ ] Patched ONNX exists under HF cache: `model.coreml_b20_s512.onnx`
- [ ] `ctx doctor .` reports accel OK
- [ ] Embeddings work via `ctx search` / MCP

---

## If CoreML still fails after option fix

Next likely issues (in order):

1. **ONNX patch failed** — check HF cache for `model.coreml_b20_s512.onnx`; if missing, debug `prepare_coderank_onnx_for_coreml()`.

2. **Dynamic shape still in graph** — may need to fix more input names or output shapes; inspect ONNX with `onnx` CLI.

3. **Sequence length** — CodeRank may need different `CTX_COREML_STATIC_SEQ` if 512 wrong for model.

4. **ORT version** — `pip show onnxruntime`; CoreML EP requires macOS 10.15+; Apple Silicon recommended.

5. **FastEmbed internal CPU fallback** — even with gpu_only providers, ORT may retry CPU on session error; setup must **fail loudly** instead of silent fallback (consider hard-fail in `accel.calibrate_batch` when CoreML requested but CPU used).

6. **`accel.py` sets `coreml_compute_units: ALL` on Apple Silicon** (line ~421) — may prefer ANE over GPU; consider forcing `CPUAndGPU` for explicit Metal.

---

## Open items / not blocking Mac GPU

| Item | Status |
|------|--------|
| npm `scubiee` publish | Not done (404) |
| PyPI 0.2.8 with CoreML fix | Pending after Mac verify |
| 10 MCP/SDK tests fail on Windows | Not blocking Mac |
| GitHub `PYPI_API_TOKEN` secret | Optional CI publish |

---

## Cursor prompt for Mac (paste this)

```
Read docs/mac-gpu-install-handoff.md first.

We need Mac CoreML GPU working on Apple Silicon — NOT CPU fallback.

Known bugs in 0.2.7 (may already be fixed on branch):
1. packages/pipeline/coreml_mac.py — remove invalid ORT options UseCPUAndGPU and CreateMLProgram
2. Same file — shape = [batch, seq] in prepare_coderank_onnx_for_coreml()

After fix:
- rm ~/.context-engine/accel.json
- ctx setup --repair must NOT print "Falling back to CPUExecutionProvider"
- Verify accel.json profile=coreml
- Run tests/test_coreml_mac.py
- Consider failing setup loudly if CoreML EP unavailable when profile=coreml

User machine: MacBook Air, Apple Silicon, Python 3.12, venv ~/.context-engine/venv
```

---

## Version history (Mac GPU)

| Version | Mac GPU status |
|---------|----------------|
| 0.2.6 | CoreML crashes on dynamic shapes / variable batch |
| 0.2.7 | Static shape approach added; **invalid ORT options → silent CPU fallback** |
| 0.2.8 | Fix invalid options + shape bug (this handoff) |

---

## Related docs in repo

- `README.md` — install overview
- `docs/publish-setup.md` — PyPI/npm publish
- `scripts/mac-install.sh` — venv + git pip fallback
- `docs/reindexing/` — live reindexing (separate from Mac GPU issue)

---

*Generated for handoff: Mac GPU install debugging, 2026-08-19.*
