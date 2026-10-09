# Scubiee engine warm-up investigation

Question: after a cold start (reboot / idle-stop), where does the time go before
the engine is fully ready (dense map/pack), and can it be cut? Build 0.3.132,
Windows, DirectML (AMD/NVIDIA discrete GPU, device_id 1), 7855 chunks, CodeRankEmbed.

## Measured cold-start timeline (live engine.log, real reboot path)

| t (s) | event |
|---|---|
| 0.0 | engine spawn requested (WMI) |
| ~1.4 | engine process alive + HTTP listening (Python import + spawn) |
| ~2.5 | `load_engine chunks=7855 ms=1109 caller=publish_engine` → **SOFT-READY** (BM25/FAISS map+search usable) |
| ~6.2 | `[embed] plan` (embedder object constructed on the prewarm thread) |
| **~20** | `[embed] loading FastEmbed` ← **~14 s gap** |
| ~22.6 | `FastEmbed ready in 2611ms` → **DENSE-READY** |

So: **soft-ready ~2.5–4.4 s** (already good — map/search/pack run on BM25/FAISS
immediately). **Dense-ready ~11–23 s**, dominated by a **~14 s gap** between the
embedder being *planned* and the ORT/DirectML session actually *loading*.

## Phase attribution (isolated, fresh process)

| phase | cost | note |
|---|---|---|
| import `pipeline.engine` | ~0.9 s | Python + numpy/faiss/fastembed import graph (floor) |
| `resolve_runtime` | ~4 ms | loads saved accel profile, no detection |
| `register_coderank` | ~0.5 s | FastEmbed custom-model registration |
| `load_engine` (binder: chunks+BM25+FAISS+graph) | ~1.1–2.0 s | soft-ready gate |
| `TextEmbedding(...)` ctor (`lazy_load=True`) | ~3 ms | deferred |
| **first inference (real ORT/DML session build + encode)** | **~1.6 s** | the actual embedder cost |
| second inference (steady) | ~28 ms | |
| full `prewarm_embedder()` end-to-end (fresh proc) | ~8.3 s | includes a redundant binder load + prime |

## Root cause of the ~14 s gap — NOT the 7k embeddings, NOT the ORT session

The 7k embeddings are **already on disk in FAISS** and load in the ~1.1 s
`load_engine` (they are not re-embedded at startup). The isolated ORT/DirectML
session builds in only **~1.6–2.6 s**. So the ~14 s gap is **neither**.

It is **GIL/scheduling contention during startup**: the prewarm runs on a daemon
thread, but ONNX Runtime session init and the DirectML first-inference hold the
GIL, while the engine is simultaneously serving a `/health` poll storm (the MCP
bridge + status polls hit `/health` every few hundred ms) and firing
`/v1/embed/keepalive` ticks. The prewarm thread is constructed early (`[embed]
plan` at ~6 s) but is starved of CPU/GIL until the poll storm settles (~20 s),
then the session builds in its ~2.6 s. The `accel=dml@Nonet/s` on the plan line
confirms a first-run path with no cached throughput hint.

Contributing factors found:
- `prewarm_embedder` calls `load_engine(root)` **without base_dir** (`base_dir=n`
  in the log). `_engine_key` resolves `None`→store_dir so in the *live* engine it
  is a cache hit (the startup binder is reused — verified: only one
  `caller=publish_engine` load in the live log). In a *fresh* process it loads a
  second binder (~1.6 s) — only affects isolated tests, not the live path.
- `[keeper] ast bundle revalidated ms=16000–33000` runs in the background **after**
  dense-ready. It does not block map/pack (heatmap serves from the prior bundle)
  but is heavy background CPU for 16–33 s and competes with the embedder warm.

## Research — faster warm-up techniques (with sources)

- **ORT session creation is inherently slow on GPU EPs the first time**
  (graph optimization + kernel/shader compilation). Multiple ORT issues report
  DirectML/CUDA `CreateSession` taking seconds to minutes cold
  ([onnxruntime#16473](https://github.com/microsoft/onnxruntime/issues/16473),
  [#9990](https://github.com/microsoft/onnxruntime/issues/9990)). Content rephrased
  for licensing compliance.
- **EPContext / `optimized_model_filepath` cache**: ORT can serialize the
  optimized graph so later sessions skip re-optimization, "greatly reduc[ing]
  session creation time" ([ORT EP-Context Design](https://onnxruntime.ai/docs/execution-providers/EP-Context-Design.html),
  [graph-optimizations](https://onnxruntime.ai/docs/performance/model-optimizations/graph-optimizations.html)).
  Caveat: a DirectML/NCHWc-optimized serialized model is **hardware-specific**
  ("should only be used in the same environment") — usable as a per-machine cache
  but risky to ship. Rephrased for compliance.
- **DirectML shares a D3D12 device/queue**; first init pays device+queue creation
  ([GPUOpen ONNX/DirectML guide](https://gpuopen.com/learn/onnx-directlml-execution-provider-guide-part1/)).
- **FastEmbed** already uses `lazy_load=True`; the cost is the first `embed()`.

**Conclusion from research + profiling:** the ORT session itself (~2.6 s) is at
the floor for a cold GPU session; the big lever here is **not** ONNX internals but
the **~14 s scheduling gap** — getting the prewarm thread the CPU/GIL sooner and
reducing the startup poll-storm contention.

## Optimization opportunities (ranked)

1. **Kick the embedder prewarm immediately on engine open, off the HTTP/keeper
   critical path** — so the ORT session starts building at ~2.5 s (right after
   soft-ready) instead of ~6–20 s. Highest potential: could move dense-ready from
   ~11–23 s toward ~5–6 s (soft-ready + session build).
2. **Quiet the `/health` + keepalive poll storm during warm-up** so the prewarm
   thread isn't GIL-starved. The keepalive loop should not tick embed work until
   the embedder is loaded (it already guards this, but the poll frequency still
   competes for the GIL).
3. **Per-machine ORT optimized-model cache** (EPContext) — shave the ~2.6 s ORT
   session build on the 2nd+ cold start. Medium potential, medium risk
   (hardware-specific cache; needs invalidation on driver/GPU change).
4. (Not warm-up but noted) **AST bundle revalidate** 16–33 s background — already
   off the critical path; the incremental-bake work is tracked separately.

## Implemented: eager-but-deferred dense prewarm

**Change** (`packages/pipeline/ce_service.py`, end of `_warm_registered`): after
soft-ready, schedule `prewarm_embedder_async` on a **0.5 s one-shot timer**
(`CTX_EAGER_PREWARM=1` default, `CTX_EAGER_PREWARM_DELAY_S=0.5`). The old code
deliberately did *not* prewarm at open (a *synchronous* load GIL-starves HTTP →
first map returns warming for 30–50 s). The async prewarm runs on a daemon
thread, so this keeps that protection while starting the ORT/DirectML session
right after soft-ready instead of waiting for an external client/keepalive
trigger. Opt-out: `CTX_EAGER_PREWARM=0`.

**Effect (verified in engine.log):** `[embed] plan` now fires **~1 s after
soft-ready** (was ~4 s, waiting for the keepalive trigger) — the prewarm is
kicked promptly and off the HTTP critical path.

## Benchmark — cold start, before vs after (3 runs each)

| metric | before | after |
|---|---|---|
| soft-ready | 4.1–4.4 s | 4.2–5.5 s |
| dense-ready | 10.5–11.7 s (up to ~23 s on the reboot path) | 10.7–12.3 s |
| `[embed] plan` fires | ~4–6 s after start | **~1 s after soft-ready** |

## Honest conclusion — where the time really is, and the ceiling

- **The 7k embeddings are NOT the bottleneck.** They live in FAISS on disk and
  load inside the ~1.1 s `load_engine`. Soft-ready (map/search/pack on BM25+FAISS)
  is ~4 s and already good.
- **Dense-ready is dominated by the DirectML/ORT first-session build**, which the
  profiling + ORT issue tracker show is a genuine cold-start floor (DX12 device +
  queue creation + kernel/shader compilation). Isolated it looked like ~1.6 s, but
  in the live engine — first ORT session in a fresh process, competing for the GIL
  with the `/health` poll storm — the plan→loading→ready span is ~12 s. This is an
  **ONNX Runtime / DirectML driver cost, not Scubiee logic**, so it cannot be
  eliminated in Python.
- **What the fix does buy:** it removes the *trigger* latency (prewarm now starts
  ~1 s after soft-ready instead of waiting ~4–6 s for a client/keepalive tick),
  which tightens dense-ready variance and shaves the worst-case (the ~23 s reboot
  path collapses toward ~11 s). It does not — and cannot — remove the DML session
  build itself.
- **Why this barely matters in practice:** the watchdog/supervisor auto-starts
  the engine on boot and it warms in the background, so by the time you open Kiro
  the engine is already dense-ready (observed: `warm_elapsed_ms` ~70 s at first
  interaction). A live session then holds it warm. You only ever *wait* for
  dense-ready if you act within the first ~10 s after a cold boot/idle-stop, and
  even then map/search/pack work immediately on the soft (BM25) lane.

### Higher-effort lever, evaluated and deferred (with rationale)
**Per-machine ORT optimized-model / EPContext cache** could shave the ~2.6 s ORT
session build on 2nd+ cold starts by serializing the DML-optimized graph
([ORT EP-Context](https://onnxruntime.ai/docs/execution-providers/EP-Context-Design.html)).
Deferred because: (a) the DML-optimized serialized model is **hardware-specific**
("use only in the same environment") and must be invalidated on GPU/driver change
— a correctness/robustness risk; (b) it needs wiring through FastEmbed's session
options, which Scubiee doesn't control directly; (c) it only targets ~2.6 s of a
cost that the supervisor already hides from the user. Not worth the risk for the
marginal, rarely-paid benefit. Documented for a future dedicated pass.

**Verdict:** warm-up is reasonable. Soft usability ~4 s, dense ~11 s, and the
supervisor pre-warms it before you interact. The eager-prewarm change removes the
avoidable trigger delay; the residual is the DirectML session-build floor, which
is an ORT/driver cost outside Scubiee's control.

## Update — deeper fix: eliminate the redundant binder reload in prewarm

Instrumenting `prewarm_embedder` with per-step timing revealed the "plan→loading"
gap was **two** costs, not one:
```
[prewarm-dbg] start load_engine      t=+7ms
[prewarm-dbg] load_engine done       t=+3553ms   ← 3.5 s REDUNDANT binder reload
[prewarm-dbg] calling embed_one      t=+3583ms
[prewarm-dbg] embed_one done         t=+10913ms  ← 7.3 s ORT/DML session build
```
`prewarm_embedder` called `load_engine(root)` again; its cache key missed the
engine `publish_engine` had already loaded, so it re-read chunks/FAISS/graph
(~3.5 s) *before* the ORT session even started.

**Fix:** the eager prewarm now warms the **already-live `self.engine.embedder`**
in place (`emb.embed_one(...)` on a daemon thread) instead of calling
`prewarm_embedder_async` → `load_engine`. Same embedder object map/search use;
no reload.

**Result (verified in engine.log):** the plan→loading gap **halved from ~12.4 s
to ~6.4 s**, and the log now shows **only one `load_engine`** (caller=publish_engine)
— the redundant reload is gone.

| metric | original | eager kick only | eager + no-reload |
|---|---|---|---|
| plan→loading gap | ~14 s | ~12.4 s | **~6.4 s** |
| redundant `load_engine` in prewarm | 3.5 s | 3.5 s | **0 (eliminated)** |
| dense-ready total | 10.5–23 s | 10.7–13.3 s | 10.5–11.3 s |

Note: total dense-ready is still ~11 s because (a) the ORT/DirectML session build
(~6–7 s under GIL contention) is the irreducible floor, and (b) engine spawn +
soft-ready has its own ~4–6 s variance (WMI spawn, disk). The fix removed the
one clearly-wasteful piece (the 3.5 s reload); the rest is the driver/ORT floor.

**Bottom line for the user:** the avoidable waste (trigger delay + redundant
binder reload, ~5–7 s combined worst-case) is eliminated. What remains is the
DirectML session build, which no Python change can remove — and which the
watchdog already pays in the background before you interact.
