# Scubiee 0.3.90 production ship

**Date:** 2026-09-15  
**Base:** 0.3.89 preprod + Mac Gate M / sim fixes on `main` through `b8f3901`

## Cross-platform soft-path verdict

**SHIP** soft-path / MCP production for Windows + macOS.

| Platform | Evidence | Result |
|----------|----------|--------|
| Windows | `_preprod_0_3_89_win_prodcheck` + `_preprod_0_3_89_win_sim_realistic` | Conditional READY → sim battery PASS |
| macOS | `_preprod_0_3_89_macos/REPORT.md` + `sim_full/SIM_REPORT.md` | Gate M READY; full sim PASS after unload/reconnect harness fixes |

## Included since PyPI 0.3.89

- `trace_lab.multi_seed` (CLI pack import)
- Gate B runner skip-missing + BM25 cache miss fix
- Host-sim unload no longer polls `/health` (false UNLOAD_TIMEOUT)
- e2e idle-reconnect health poll race fix
- Windows wipe shim sweep, Codex TOML, blink disk cache (already in 0.3.89 tree)

## Explicitly not claimed

- Gate E full pytest (advisory)
- Live Cursor IDE click-through re-time
- Unconditional doctor green on dirty-journal worktrees

## Publish status (2026-09-15)

| Surface | Status |
|---------|--------|
| GitHub `main` | pushed `9b3f9a3` |
| Tag `v0.3.90` | pushed |
| Local `python -m build` | wheel+sdist ok (`trace_lab/multi_seed.py` in wheel) |
| GitHub Actions `publish` | **FAILED** (pypi + npm) — same pattern as recent `v0.3.1x` tags; needs valid `PYPI_API_TOKEN` / `NPM_TOKEN` or trusted-publishing fix |
| PyPI `scubiee==0.3.90` | **LIVE** — uploaded 2026-09-15 via local `uv publish` using `.env` `pipy_*` |
