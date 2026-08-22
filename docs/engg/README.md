# Engineering (`docs/engg`)

Canonical **how the product works** for a new session. Historical plans live under `docs/superpowers/`; Mac benches stay as data files. Session memory lives in [`../session-info/`](../session-info/).

| File | Read when |
|------|-----------|
| [01-vision.md](./01-vision.md) | Why Scubiee / Context Engine exists and how we measure “done” |
| [02-tech-summary.md](./02-tech-summary.md) | Architecture, pipeline, MCP, GPU, processes, storage |

**Product today:** `scubiee==0.2.33`. Branch `feat/production-certification`. Embed weights are **FP16 only** everywhere (MLX FP16 on Apple Silicon; FastEmbed `onnx/model_fp16.onnx` on CUDA/DirectML/CPU/CoreML). Windows GPU is **DirectML**. Setup warns if another `scubiee.exe` is on PATH; leftover ORT folders are purged on wheel swap.
