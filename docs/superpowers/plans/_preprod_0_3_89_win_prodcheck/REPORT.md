# Scubiee 0.3.89 Windows production check (real CLI + sim)

**Date:** 2026-09-15  
**Install:** `uv tool install --force .` (source tree with serious fixes)  
**Harness:** real `scubiee` CLI, `mcp_host_sim.py`, `warm_contract_acceptance.py`, `scubiee_mcp_ship_check.py`, `run_cli_combination_tests.py`, curated e2e via uv-tool python — **not** in-process unit mocks for ship decision.

## Verdict

**Windows soft-path ship: READY (conditional)** — Gates **A–D** green on real CLI/sim after reinstall.  
Not unconditional cross-platform production: Gate **E** still advisory; Gate **M** (macOS) not run; live Cursor smoke (Gate Task 7) not re-timed in this pass.

| Gate | Result | Evidence |
|------|--------|----------|
| **A** Env | **PASS** | `scubiee 0.3.89`; soft_search_ready=true; chunks=6952; CPU cap 20% |
| **B** Curated e2e | **PASS** | `run_scubiee_e2e_suite.py` ok=True (uv-tool python + pytest) |
| **C** MCP + availability | **PASS** | host-sim Lane A ok; warm_contract 0 failed; ship_check ladder ok |
| **D** CLI journey | **PASS** | `run_cli_combination_tests.py --quick` **30/30** |
| **E** Full pytest | **advisory** | Prior 34 fails triaged; serious product bugs fixed; not re-run full suite this pass |
| **W** Windows | **PASS (practical)** | host-sim + pythonw bridge + CPU 20 exercised |
| **M** macOS | **Not run** | Darwin required |

## Host-sim SLAs (this run)

| Phase | Result |
|-------|--------|
| soft_ready from host_start | **~2.9 s** |
| map_first | **~65 ms** |
| pack_first | **~63 ms** |
| expand_first | **~0.65 s** |

## Notes

- Before reinstall, installed uv-tool package **lacked** the Codex/TOML, bridge-verify, WinError-193, setup-dedup fixes — unit tests against `packages/` were green but **production binary was stale**. Always reinstall before claiming ship.
- `binaries_match: false` when PATH hits `.local\bin\scubiee` vs `Scripts\scubiee.exe` (or `.exe` suffix compare) — prefer invoking `...\Scripts\scubiee.exe` for Gate A doctor cleanliness.
- CLI combo stops the engine; re-`engine ensure` before claiming soft-ready.
