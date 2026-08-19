# Engineering (`docs/engg`)

Canonical **how the product works** for a new session. Historical plans live under `docs/superpowers/`; Mac benches stay as data files. Session memory lives in [`../session-info/`](../session-info/).

| File | Read when |
|------|-----------|
| [01-vision.md](./01-vision.md) | Why Scubiee / Context Engine exists and how we measure “done” |
| [02-tech-summary.md](./02-tech-summary.md) | Architecture, pipeline, MCP, GPU, processes, storage |

**Product today:** tree `scubiee==0.2.18`, PyPI latest **0.2.17**. Branch `feat/production-certification`. Apple Silicon default embed is **MLX FP16**, not CoreML. Windows GPU is **DirectML**.
