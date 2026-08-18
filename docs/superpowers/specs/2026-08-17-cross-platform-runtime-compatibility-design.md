# Cross-Platform Runtime Compatibility Design

**Status:** Approved in chat on 2026-08-17 (design sections 1–3)  
**Branch / worktree:** `feat/production-certification`  
**Related:** `questions-answered.md`, batch calibrator in `pipeline.accel`

## Goal

Make Context Engine start and run safely on Windows, Linux, and Apple Silicon Macs across NVIDIA, AMD, Intel, and CPU-only machines with different RAM sizes. The daemon must choose the best verified acceleration path for that machine, keep indexing from crashing or over-consuming memory, and still serve search from the last coherent index under pressure.

## Non-goals (foundation release)

- Guaranteeing ROCm or Apple Metal GPU acceleration before a provider/model probe passes on that machine.
- Shipping separate OS-specific daemon / ResourceManager implementations.
- Re-selecting OS stacks or batch winners on every server start.
- Making batch 20 (or 32) the global default.
- Dashboard cosmetics.

## Locked decisions

### Install once, run that profile, CPU as backup (user intent)

This is the product shape:

1. **All choosing happens once at installation** (`ctx setup` / `ctx init`) — and nowhere else in normal operation:
   - OS detection
   - hardware / GPU detection
   - which acceleration stack to install (CUDA / DirectML / verified-other / CPU)
   - package install for that stack
   - model warm-up
   - batch selection (8 / 16 / 20, prefer 16)
   - RAM-tier defaults written into the saved profile
   - Write `accel.json` + `hardware.json` as the machine’s permanent preferred setup
2. **After install, CE does not re-choose** OS stacks, GPU backends, or batch winners on `serve`, MCP connect, doctor (read-only), or everyday indexing.
   - Runtime **loads** the saved profile and runs it.
   - ResourceManager / FairEmbedScheduler / keeper / search are **portable** across Windows, Linux, and macOS — same code paths, same pressure policy. They consume the installed profile; they do not pick a new stack.
3. **OS- and hardware-specific work is install-only.**
   - Install-only examples: ORT wheel selection, DirectML vs CUDA package, provider device id, batch calibration, first model download.
   - Runtime-portable examples: dirty journal, RepoHub, fair embed queue, envelope demotion, publication manifest, search serving.
4. **CPU is the emergency backup for occasional runtime failure**, not a second chooser.
   - If the saved accelerated session fails (provider error, OOM, driver glitch):
     - keep search up from the last coherent index;
     - for this process/session only, use a **temporary CPU safety path** and/or demoted batch with an explicit status reason;
     - do **not** rewrite `accel.json` / reinstall stacks / re-calibrate batch for a transient fault;
     - next healthy start uses the **original installed preferred profile** again.
   - Permanent re-choice requires explicit re-install / `ctx init` / repair — never an ambient background re-pick.

```text
INSTALL (once, all selection)
  detect OS + hardware
  → choose + install stack for THIS machine
  → warm model
  → calibrate batch
  → save preferred profile forever (until explicit re-init)

RUNTIME (normal, no choosing)
  load preferred profile
  → portable ResourceManager / scheduler / indexing / search
  → serve

RUNTIME (occasional fault only)
  preferred accel fails
  → temporary CPU/demoted backup (in-process)
  → status explains why
  → preferred install profile UNCHANGED
  → recover to preferred on next healthy start
```

### Compatibility model (§1)

1. During **install**, CE builds a hardware snapshot: OS, architecture, RAM total/available, CPU cores, GPU/provider availability, and installed backend versions.
2. Backend candidates are evaluated **once** in this order:
   - Windows NVIDIA → CUDA
   - Windows AMD/Intel/NVIDIA → DirectML
   - Linux NVIDIA → CUDA
   - Linux AMD → only a validated ROCm/ONNX provider
   - Apple Silicon → only a validated Apple-compatible provider
   - Otherwise → bounded CPU
3. A candidate is accepted only after:
   - the ORT provider is actually available, and
   - a real CodeRankEmbed warm-up + throughput probe succeeds.
4. Results persist as the machine’s preferred profile in `~/.context-engine/accel.json` (plus `hardware.json`).
5. If **install** validation fails, CE never crashes and never silently claims acceleration. It records why and saves a conservative CPU profile as the preferred profile.
6. At **runtime**, if the preferred accelerated profile cannot be used, CE uses the CPU backup path for that session and reports why; it does not pretend the GPU is healthy.
7. Under pressure, CE reduces work / defers indexing while serving the last coherent search generation.
8. `ctx doctor` / server status expose: preferred backend, active backend (preferred vs temporary backup), verified provider, batch/workers, memory envelope, fallback reason, and the exact recommended server command.

### Adaptive resource envelopes (§2)

Limits derive from **available memory**, not total RAM alone.

| Tier | Trigger | Policy |
|---|---|---|
| Low | ≤8 GB total RAM **or** &lt;3 GB currently available | Batch ceiling 1–4 (or calibrated ≤8 if proven), one embed worker, one indexing repo at a time, aggressive model unload, bounded queues, search first |
| Standard | ~12–24 GB RAM with healthy free memory | Measured batch up to **16**, one embed worker, limited extraction parallelism, unload after configurable idle |
| High | ≥32 GB RAM with adequate free memory | Use benchmarked safe batch (usually 16, 20 only if calibration promoted it), more parsing workers, still one fair-scheduled accelerator owner |

Continuous sampling: RAM, CPU load, swap pressure, and GPU memory where reliable. Hysteresis prevents oscillation.

Pressure actions (ordered):

1. Reduce future batch size  
2. Reduce parser/index workers  
3. Pause background indexing  
4. Unload the embedding model  
5. Keep daemon + BM25/graph/vector search alive  

Embed OOM: one smaller-batch retry, then quarantine that batch/profile step and switch to a verified lower setting. No retry loops. No silent backend swaps. User overrides are **ceilings**, not permission to exceed measured safety.

### Install-time batch calibration (approved addendum)

- Candidates: **8, 16, 20** (not 32 as default).
- Prefer **16**.
- Promote to **20** only if throughput gain is ≥10% **and** ≥+3 t/s vs 16.
- Downgrade to **8** only if 16 fails or is ≥15% slower than 8.
- Uses CE-like ~700-char chunks; model loaded once; target wall time well under 30s for the probe.
- Evidence on the development DML laptop: 20 was only ~2–3% faster than 16 → winner **16**.

### Packaging, startup, certification (§3)

**Packaging**

- Optional extras remain mutually exclusive where ORT wheels conflict: `[cuda]`, `[dml]`, `[cpu]` (default path).
- `ctx setup` / `ctx init` always:
  1. hardware snapshot  
  2. provider install for chosen profile  
  3. model warm-up  
  4. batch calibration (8/16/20, prefer 16)  
  5. write `accel.json` + `hardware.json`

**Server startup**

- Doctor/status emit the recommended command for the **installed preferred** profile, for example:
  - Windows DML: `ctx init --profile dml` then `ctx serve`
  - Linux CUDA: `ctx init --profile cuda` then `ctx serve`
  - CPU / unverified GPU: `ctx init --profile cpu` then `ctx serve`
- Daemon **loads the saved preferred profile** (no re-pick). It applies the RAM envelope.
- If the preferred accelerated provider is missing or fails to warm:
  - activate **temporary CPU backup** for this process;
  - surface `preferred_profile` vs `active_profile` + reason;
  - do not rewrite the preferred install choice unless the user re-runs init/repair.
- Search remains available from the last coherent index while indexing is deferred or on backup.

**Certification matrix**

| Lane | Required |
|---|---|
| Windows CPU / DML / CUDA* | init + calibrate + doctor + serve smoke |
| Linux CPU / CUDA* | same |
| Linux AMD | CPU-safe path required; GPU only if provider validates |
| macOS Apple Silicon | CPU-safe path required; GPU only if provider validates |
| RAM tiers low/standard/high | deterministic envelope unit tests + native lab where possible |

\*CUDA lanes run when hardware exists; otherwise skip neutrally (never counted as pass).

## Architecture

```text
INSTALL (once)
  detect OS/hardware → install stack → probe → calibrate batch → save preferred profile

RUNTIME (normal)
  load preferred profile → apply RAM envelope → serve/index
  (no re-choose / no re-calibrate)

RUNTIME (occasional fault)
  preferred accel fails → temporary CPU/demoted backup → status explains why
  → preferred profile in accel.json stays unchanged
  → recover to preferred on next healthy start / after repair
```

## Components

| Component | When it runs | Responsibility |
|---|---|---|
| `pipeline.hardware` | **Install** (snapshot); runtime may **read** only | Snapshot RAM/CPU/platform |
| `pipeline.accel` configure / calibrate | **Install only** | Choose stack, install packages, probe, batch calibration, persist preferred profile |
| `pipeline.accel` load / resolve | Runtime | Load saved preferred profile (no re-choose) |
| `pipeline.resources` | Runtime (portable) | Envelope/pressure using saved batch as ceiling; same logic on all OSes |
| `pipeline.fair_schedule` | Runtime (portable) | Single-flight embed ownership |
| Keeper / RepoHub / search / journal | Runtime (portable) | OS-agnostic product behavior |
| Temporary CPU backup | Runtime fault only | In-process safety net; does not reinstall or rewrite preferred profile |
| `pipeline.doctor` / `certify` | Anytime | Report preferred vs active; recommend re-init only when repair needed |
| CLI `init` / `setup` | Install / explicit repair | Only place that chooses stacks |
| CLI `serve` | Runtime | Start with saved profile |

## Error handling

- Missing accelerated provider at **install** → save CPU as preferred with clear reason.
- Missing/failing accelerated provider at **runtime** → temporary CPU backup; keep preferred accel in `accel.json`; doctor shows both.
- Forced profile at install that cannot validate → clear error + repair hint; do not pretend success.
- Calibration failure → keep prefer batch 16 (or profile default) and record error in `batch_calibration`; do not crash install.
- Runtime OOM → one demotion retry, then temporary lower batch / CPU backup; search stays up; preferred profile unchanged.

## Testing strategy

1. **Unit:** `pick_batch_size` ROI rules; envelope tier selection from simulated free/total RAM; fail-closed provider checks.
2. **Integration:** `configure(bench=True)` writes calibration block; doctor reads it.
3. **Native labs:** Windows DML (existing), Linux CUDA when available, macOS CPU path; skips are neutral.
4. **Regression:** accelerated profile must not silently fall back to PyTorch CPU.

## Acceptance criteria

1. **Install is the only chooser:** OS stack, GPU backend, packages, and batch are selected during `ctx init` / `setup` and persisted.
2. **Runtime does not re-choose** stacks or batch winners on serve/MCP/index; ResourceManager is portable and only applies envelopes/pressure to the saved profile.
3. Occasional accel faults use a **temporary CPU backup** without erasing or reinstalling the preferred profile.
4. Wrong/missing accel never silently becomes “fast GPU.”
5. Batch choice is measured at install and biased to 16.
6. Under memory pressure, CE demotes work in the ordered §2 steps and keeps search up (portable policy on all OSes).
7. `ctx doctor` shows preferred vs active backend, batch, envelope tier, fallback reason, and exact run command.
8. Certification matrix lanes pass or skip neutrally; skips never increase passed count.

## Implementation notes (already landed)

- Prefer-16 batch calibrator (`calibrate_batch` / `pick_batch_size`) is implemented in `packages/pipeline/accel.py` and wired into `configure()` when `bench=True`.
- Remaining work for this design: envelope tiers tied to **available** RAM, doctor command surfacing, Linux AMD / Apple Silicon verified-or-CPU paths, and cert matrix expansion.
