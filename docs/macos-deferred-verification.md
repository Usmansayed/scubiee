# macOS deferred verification checklist

**Date:** 2026-08-26  
**Purpose:** Short checklist for Mac-only tests.  
**Full context + handoff for Mac Cursor:** see **`docs/mac-cursor-session-handoff-2026-08-26.md`** (what we are doing, Windows status, exact Mac steps, report table).

Run from repo root after installing the wheel/version under test:

```bash
uv tool install --force scubiee==<version> --index-url https://pypi.org/simple
scubiee setup --repair
```

---

## Must-run on Mac (Apple Silicon)

| # | Command / test | What “pass” looks like |
|---|----------------|-------------------------|
| 1 | `scubiee setup --repair` | Profile **`mlx`** (not `cpu`). Setup finishes without hang. |
| 2 | `scubiee setup --status` / Desktop diagnose JSON | `acceleration.profile == "mlx"`, libraries include mlx / onnxruntime / fastembed as expected |
| 3 | `scubiee init .` in a small repo | Index completes; daemon healthy |
| 4 | `scubiee connect --cursor` (or `--kiro`) | MCP + rules written; agent `status()` → `managed: true` |

**Open (2026-08-26):** Mac pytest / MLX looked good, but **non–special-4 connect** (esp. Cursor global `${workspaceFolder}`) can leave `status.managed=false` — Cursor may **not** expand the token. Details + next fixes: [`mac-session-2026-08-26-workspace-token-issue.md`](./mac-session-2026-08-26-workspace-token-issue.md). Special-4 (kiro / copilot / cline / roo) project pins are the working path.

| 5 | Forced wrong path: `scubiee setup --profile cpu` then `scubiee setup --repair` | Should restore Mac GPU path (MLX) — never stay CPU-only on Apple Silicon |

---

## Pytest modules (Mac host) — run existing files; do not rewrite

```bash
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python -m pytest \
  tests/mac_production_test.py \
  tests/test_coreml_mac.py \
  tests/test_mlx_backend.py \
  tests/test_cross_platform_profiles.py \
  -q --tb=short
```

| Module | Why Mac |
|--------|---------|
| `tests/mac_production_test.py` | Multi-repo / permissions / live Mac paths |
| `tests/test_coreml_mac.py` | CoreML / CodeRank ONNX graph validation |
| `tests/test_mlx_backend.py` | MLX import + embed path |
| `tests/test_cross_platform_profiles.py` | M-series recommend profile stays `mlx` |

Optional:

```bash
python -m pytest tests/test_mcp_locate.py::test_live_search_read_flow -q
```

---

## Product behaviors to spot-check on Mac

1. Never demote Apple Silicon to CPU.
2. `scubiee resume` (not `wake`) after `scubiee stop`.
3. Mid-session `scubiee init` → agent retries `status()` once (not every turn).
4. Stop engine before `uv tool install --force` / `scubiee upgrade`.

---

## Do **not** require Mac for

- Windows CPU-only / DirectML validation (done)
- Journey P0/P1 status/warming/templates (done on Windows)
- Full Windows pytest (`692 passed` as of 2026-08-26)

---

## Record results here when run

| Date | Machine | scubiee version | Setup profile | Init/connect | Pytest summary | Notes |
|------|---------|-----------------|---------------|--------------|----------------|-------|
| 2026-08-26 | Mac17,3 / Apple M5 | 0.2.82 (from repo via uv) | mlx | PASS (tiny repo + connect --cursor) | 38 passed, 4 failed | See `docs/mac-cursor-session-handoff-2026-08-26.md` §4 for failure names. Setup never stayed on cpu. |
