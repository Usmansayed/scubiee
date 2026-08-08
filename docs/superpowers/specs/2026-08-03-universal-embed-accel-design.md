# Universal embed accel (FastEmbed + hardware detect)

Date: 2026-08-03

## Goal

Ship Context Engine so a user can install in one command; the product detects
hardware, installs the right ONNX Runtime wheel, downloads CodeRankEmbed ONNX,
and aims for ≥10 texts/sec on GPU-class machines.

## Decision

- **Backend:** FastEmbed + CodeRank ONNX (`jamie8johnson/CodeRankEmbed-onnx`)
- **Profiles:** `cuda` | `dml` | `cpu` (mutually exclusive ORT packages)
- **Install paths:** `scripts/install.ps1` / `install.sh` **and** `pip install -e .` + `pipeline init`
- **Persist:** `~/.context-engine/accel.json`
- **Merkle / incremental:** existing Python pipeline (CC idea), not TS vendor at runtime

## Detect order

1. NVIDIA (`nvidia-smi` / torch) → `cuda`
2. Windows + display adapters → `dml` (pick discrete-looking adapter id)
3. Else → `cpu`

## Non-goals (v1)

- ROCm / CoreML first-class extras (can add later)
- Multi-session DML parallelism (proven slower)
- Bundling Graphify into PyPI without vendor clone
