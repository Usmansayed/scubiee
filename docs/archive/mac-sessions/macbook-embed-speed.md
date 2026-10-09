# MacBook embed speed vs Windows — full session notes

> Written 2026-08-19 from the Mac install + speed debugging chat on `feat/production-certification`.
> Companion install handoff: [`mac-gpu-install-handoff.md`](./mac-gpu-install-handoff.md).

---

## What this file is

A complete recap of everything we hit while putting Context Engine (`scubiee`) on an Apple Silicon MacBook Air, why embedding looked “on GPU” but was painfully slow, and why an older Windows laptop felt faster.

If you only need the punchline: **Mac CoreML was not a real Metal win.** It ran the CodeRank ONNX graph as ~49 tiny GPU/CPU partitions because of empty RoPE slices. That was ~0.4 chunks/s. **Apple Silicon CPU FastEmbed is the fast path today** (~13–18 chunks/s, ~2,100 tok/s). Indexing this repo finished in about **3.4 minutes**. Windows DirectML at ~30 texts/s was faster than broken CoreML, not faster than this Mac’s CPU.

---

## Machines and env

| | Windows (earlier) | MacBook Air (this session) |
|---|---|---|
| OS | Windows | macOS 26.5.2 (darwin 25.5.0), arm64 |
| GPU path | DirectML (`DmlExecutionProvider`) | CoreML → Metal (`CoreMLExecutionProvider`) |
| Typical speed (project `t/s`) | ~30 texts/s on an older laptop | CoreML ~0.4 texts/s (broken); CPU ~13.5–17.6 texts/s |
| Python | — | 3.12.14 (Homebrew) |
| Package | scubiee 0.2.6 → 0.2.7 on PyPI | this branch as editable **0.2.8** |
| ONNX Runtime | DirectML wheel | `onnxruntime` 1.29.0 (includes CoreML EP) |
| FastEmbed | 0.8.0 | 0.8.0 |
| Model | `nomic-ai/CodeRankEmbed` via `jamie8johnson/CodeRankEmbed-onnx` | same |

**Python venv (easy to get wrong):**

| Path | Reality |
|---|---|
| `~/scubiee` | Does **not** exist (handoff doc assumed this) |
| `~/.scubiee/venv` | Created first; **Python 3.9.6, empty** — do not use |
| **`~/venv`** | The real env: Python 3.12.14, `scubiee[coreml]==0.2.7` then editable 0.2.8 |
| `~/.context-engine/venv` | Default npm/mac-install.sh location — **not used** |
| `~/.context-engine/` | Runtime state: `accel.json`, indexes, vectordb |

Always:

```bash
export PATH="$HOME/venv/bin:$PATH"
# python and ctx should be ~/venv/bin/...
```

Repos:

- Public: `https://github.com/Usmansayed/new-context-engine.git`
- This checkout: `https://github.com/Usmansayed/hidden-context-engine-.git`
- Branch: `feat/production-certification`

---

## Goal

Install `scubiee` on the MacBook Air and embed on **GPU (Metal via CoreML)**, not CPU. User explicitly rejected `ctx setup --profile cpu` as a workaround.

Later, once CoreML “worked,” indexing this folder was so slow it would take ~2 hours for ~2,800 chunks. User expected **under 5 minutes**, matching the Windows laptop feel (~30 t/s).

---

## Timeline

### 1. Windows → Mac install (0.2.5 – 0.2.7)

On Windows the engine was already production-hardening: search CLI, daemon health, live reindex, PyPI 0.2.6.

Mac install journey:

1. `pip install scubiee` (0.2.6) — install OK.
2. `ctx setup` — **failed** with CoreML errors: `E5RT`, dynamic shapes, `runtime shape ({1,6,12,0}) has zero elements`.
3. Advice was CPU profile. User refused.

Research conclusion: Mac has no CUDA. GPU = **ONNX Runtime CoreML EP → Metal**. Transformers need:

- Static input shapes (`RequireStaticInputShapes=1`)
- Fixed batch (pad; never `batch_size=len(batch)` on CoreML)
- Patched CodeRank ONNX to `[batch, 512]`
- `MLComputeUnits=CPUAndGPU` (Metal, not ANE-only)
- `CTX_MAC_GPU_ONLY=1` to keep CPU EP out of the provider list

That became **0.2.7** (`packages/pipeline/coreml_mac.py`, accel + embedder). Published to PyPI 2026-08-19.

### 2. 0.2.7 still broken on a real Mac

```bash
pip install -U "scubiee[coreml]==0.2.7"
ctx setup --repair
```

Model downloaded (~549MB). Setup printed **Ready** with calibration **21.58 t/s**. That was **misleading success on CPU**.

Exact error:

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

**Cause:** `coreml_provider_options()` passed C-API flags as string provider options:

| Bad option | Why wrong |
|---|---|
| `UseCPUAndGPU` | `COREML_FLAG_USE_CPU_AND_GPU` — not an ORT string option |
| `CreateMLProgram` | Wrong; `ModelFormat=MLProgram` already covers this |

Valid options: `MLComputeUnits`, `ModelFormat`, `RequireStaticInputShapes`, `EnableOnSubgraphs`.

**Second 0.2.7 bug:** `prepare_coderank_onnx_for_coreml()` used `shape` before it was defined. Exception swallowed → static ONNX patch never applied.

Branch **0.2.8** removed the bad options and set `shape = [batch, seq]`.

### 3. This Mac session — make CoreML actually attach

Checkout was `feat/production-certification` (already had the 0.2.8 option/shape fixes). Work on this machine:

1. Installed the repo editable into `~/venv`: `pip install -e ".[coreml]" pytest`.
2. Confirmed ORT providers: `['CoreMLExecutionProvider', 'AzureExecutionProvider', 'CPUExecutionProvider']`.
3. Made setup **fail loudly** instead of silent CPU fallback (`CTX_MAC_GPU_ONLY=1`).
4. Forced Metal units `CPUAndGPU` (not `ALL` / ANE).
5. `ctx setup --repair` with GPU env.

CoreML session **did** come up:

```
[accel] CoreML session providers=['CoreMLExecutionProvider', 'CPUExecutionProvider']
```

No more `Unknown option: UseCPUAndGPU`. No more `Falling back to CPUExecutionProvider` from invalid options.

Then two more setup bugs:

**A. FastEmbed cache ≠ Hugging Face hub cache**

Patched ONNX was written to:

`~/.cache/huggingface/hub/models--jamie8johnson--CodeRankEmbed-onnx/.../onnx/model.coreml_b20_s512.onnx`

FastEmbed loaded from:

`/var/folders/.../T/fastembed_cache/models--jamie8johnson--CodeRankEmbed-onnx/.../onnx/`

Error: `NO_SUCHFILE ... model.coreml_b20_s512.onnx`. Fix: copy/hardlink the patched file into FastEmbed’s cache (`install_patched_onnx_into_fastembed_cache`).

**B. Tokenizer length 11 vs static graph 512**

```
INVALID_ARGUMENT : input_ids index: 1 Got: 11 Expected: 512
```

FastEmbed pads to the **longest sequence in the batch**, not to 512. The static ONNX requires `[batch, 512]`. Fix: `bind_coreml_tokenizer()` → `enable_truncation(max_length=512)` + `enable_padding(length=512)`. Also pad **row count** to static batch 20.

After that, `ctx setup --repair` succeeded on CoreML. Calibration: **0.71 t/s**. Smoke embed produced a 768-d vector. That looked like “GPU works.”

### 4. Index this folder — speed falls apart

User asked to index this repo and report tokens/s.

`ctx index . --force` on CoreML:

| Batch | Rate |
|---|---|
| 16/2819 | 0.53 chunk/s, 74 tok/s, **30.4 s/batch** |
| 96/2819 | 0.41 chunk/s, 46 tok/s, 39.1 s/batch |
| 176/2819 | 0.38 chunk/s |
| 416/2819 | ~0.4 chunk/s after ~17 minutes |

ETA for 2,819 chunks: **~2 hours**. User: it should finish in **under 5 minutes**; Windows laptop was ~**30 t/s**.

CoreML index was killed. Diagnosis next.

---

## Why CoreML was so slow (the real bug)

ORT logs on every session:

```
CoreML does not support shapes with dimension values of 0.
  Input: .../rotary_emb/Slice_5_output_0, shape: {20,512,12,0}
  Input: .../rotary_emb/Slice_11_output_0, shape: {20,512,12,0}
  (12 encoder layers × 2)

CoreMLExecutionProvider::GetCapability
  partitions supported by CoreML: 49
  nodes in the graph: 646
  nodes supported by CoreML: 501
```

CodeRank / Nomic-BERT uses **full-head rotary** (`rotary_emb_fraction: 1.0`, head dim 64). The ONNX export still does:

```
Concat([-1], rotated_q,  remainder_slice)   # Concat_3
Concat([-1], rotated_k,  remainder_slice)   # Concat_7
```

`remainder_slice` is `x[..., rotary_dim:]` on axis 3. When rotary covers the whole head, that slice has **width 0**.

- **CPU and DirectML:** a 0-width concat is a no-op. Fine.
- **CoreML:** 0-size tensors are illegal. Those Slice nodes stay on CPU. The graph shatters into **~49 partitions** (GPU blob, CPU, GPU, CPU, …). Launch overhead dominates. GPU is “on” and still useless.

Same 0-dim showed up in 0.2.6 as `runtime shape ({1,6,12,0}) has zero elements`. Dynamic CoreML crashed; static CoreML “runs” by parking those ops on CPU.

### Side cost of the static CoreML recipe

Even without partitions, the Mac GPU path always runs **batch 20 × seq 512**. Index chunks are compressed (~512 chars ≈ 100–200 tokens). Windows DML uses **real batch and real sequence length**. Padding to 512 is several times more FLOPs per chunk.

---

## Head-to-head numbers (this Mac, 2026-08-19)

Microbench, 16 short snippets, same ONNX Runtime 1.29:

| Path | Timed 16 chunks | Content chunks/s |
|---|---|---|
| **CPU**, original model, natural batch 16 | 0.10 s | **155** |
| **CoreML**, static 20×512, partitioned | 38.89 s | **0.41** |

CoreML was about **380× slower** than CPU on that microbench.

Official `ctx setup` calibration (longer ~700-char snippets):

| Path | texts/s (`t/s`) |
|---|---|
| 0.2.7 silent CPU fallback (looked like CoreML success) | 21.58 |
| CoreML static (GPU “working”) | 0.71 |
| CPU profile after the switch | **17.57** (batch 16 wins; 20=17.14, 8=15.59) |

Real index of **this repo** (`hidden-context-engine-`), CPU FastEmbed:

```
[embed] done: 2565 new / 256 cached in 190.5s
         (13.46 chunk/s, 2131 content tok/s) on cpu
chunks: 2821
wall clock for ctx index --force: ~3.4 minutes
```

| Metric | Broken CoreML index | CPU index (current) | Windows DML (memory) |
|---|---|---|---|
| Chunks / s | ~0.4 | **~13.5** | ~30 texts/s |
| Tokenizer tokens / s | ~50 | **~2,100** | not separately logged |
| ~2,800 chunks | ~2 hours | **~3.2 min embed** | would be ~1.5 min at 30 t/s |

So:

- Windows **was** faster than Mac **CoreML**. That comparison was real.
- Windows was **not** faster than this Mac’s **CPU**. Apple Silicon CPU is in the same order as that old DirectML box (13–18 vs ~30 texts/s). DirectML still wins on texts/s; CoreML lost by two orders of magnitude.
- If “30 tokens per second” was meant literally (tokenizer tokens), this Mac CPU is ~2,100 tok/s — much higher. In this repo, **`t/s` almost always means texts/chunks per second**, not tokenizer tokens.

---

## Why Windows felt fast and Mac did not

1. **Different accelerators.** Windows used DirectML on a discrete/iGPU path that **can run 0-width slices**. Mac CoreML cannot.
2. **Silent CPU on 0.2.7.** First Mac “success” at 21 t/s was CPU after CoreML option rejection. That was actually OK speed — then we “fixed GPU” and speed collapsed.
3. **“GPU working” ≠ GPU fast.** After 0.2.8, CoreML was the first provider, 501/646 nodes assigned to it, embeddings numerically fine — and 40 s/batch because of 49 partitions.
4. **Static 20×512** is a CoreML compiler requirement, not how DML runs. DML embeds the real token length.
5. **Target in code is 10 texts/s** (`CTX_TARGET_TPS`). Windows ~30 clears it. CoreML 0.4 does not. CPU ~14–18 does.

There is no CUDA on Mac. Metal-via-CoreML is the only GPU story, and **this ONNX is not CoreML-friendly until empty RoPE concats are removed**.

---

## What we changed in the tree (this session)

| File | Change |
|---|---|
| `packages/pipeline/coreml_mac.py` | Valid ORT options only; `shape=[batch,seq]`; FastEmbed cache copy; tokenizer pad to 512; `bypass_empty_rotary_remainders()` (drop Slice_5/11 + Concat_3/7); patched filename `*_norot0.onnx` |
| `packages/pipeline/accel.py` | Metal `CPUAndGPU`; fail if CoreML EP missing when GPU-only; **if CoreML calibrate &lt; 10 t/s, switch to CPU FastEmbed** |
| `packages/pipeline/embedder.py` | CoreML pad + tokenizer bind; log chunk/s and tok/s even with a progress bar |
| `packages/pipeline/preflight.py` | Warm CoreML-static model with pad + tokenizer |
| `tests/test_coreml_mac.py` | Options, GPU-only, cache copy, tokenizer, rotary bypass |
| `tests/test_cross_platform_profiles.py` | Apple Silicon expects `CPUAndGPU`, no CPU EP when `CTX_MAC_GPU_ONLY=1` |

Current `~/.context-engine/accel.json` after the speed fix:

- `profile`: `cpu`
- `provider`: `CPUExecutionProvider`
- `texts_per_sec`: ~17.57
- `batch_size`: 16

---

## How to reproduce / operate now

```bash
export PATH="$HOME/venv/bin:$PATH"
# Fast path (current):
ctx setup --profile cpu --repair --skip-install
ctx index /path/to/repo --force

# Do not use CoreML for indexing until partition count collapses:
# export CTX_MAC_GPU_ONLY=1
# ctx setup --profile coreml --repair
```

Success checks for a **fast** Mac install:

- [x] Index of this repo in well under 5 minutes
- [x] `[embed] ... device=cpu` at ~10–18 chunk/s, ~2k tok/s
- [ ] CoreML session with **few partitions** (not 49) and calibrate ≥ 10 t/s — **not true yet**

---

## Remaining GPU work

`bypass_empty_rotary_remainders()` is in the patch pipeline (`Concat` of `Slice_5` / `Slice_11` → rewire to the rotated tensor). It has not been shown to make CoreML faster than CPU on this Air. Next:

1. Delete old `model.coreml_b20_s512.onnx` caches; rebuild `*_norot0.onnx`.
2. Confirm ORT log: partitions should drop far below 49; **no** `dimension values of 0` on Slice_5/11.
3. Microbench CoreML vs CPU on the same 16/64 chunks.
4. Only keep `profile=coreml` if it beats ~10 t/s (ideally approaches Windows ~30).
5. If CoreML is still slow, likely leftover dynamic Slice/RoPE ops or 20×512 padding vs short chunks — consider a CoreML-oriented export, or smaller static seq for index-sized chunks.

Until then, **Mac production embed = CPU FastEmbed.** That is not a cop-out: it is faster than the Metal path we actually got, and in the same league as the Windows DML laptop.

---

## Glossary

| Term in this project | Meaning |
|---|---|
| `t/s` / texts/s | **Chunks (embed strings) per second**, from `calibrate_batch` |
| chunk/s | Same, from indexer `embed_many` |
| tok/s / content tok/s | Sum of tokenizer `attention_mask` (real tokens, not pad) / wall time |
| GPU tok/s | On CoreML, static `20 × 512` per forward; on CPU, same as content tok/s |
| `CTX_MAC_GPU_ONLY=1` | Do not put `CPUExecutionProvider` on the CoreML provider list (does not stop ORT from using CPU for unsupported nodes) |

---

*Session machines: MacBook Air Apple Silicon, Python 3.12, venv `~/venv`. Windows numbers are from the prior DirectML trial, not re-measured in this chat.*
