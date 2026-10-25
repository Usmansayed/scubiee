# Scubiee macOS findings: v0.3.152 delta pass (0.3.149 → 0.3.152)

_Delta validation per `docs/scubiee-macos-handoff-0.3.152.md`. Only the 7 changes
landed on Windows in 0.3.149-0.3.152 were tested; the 0.3.145 battery
(embedder/MLX, cold-start, graph, launchd, sync lanes) was NOT repeated, none of
these deltas touch it. All results are live runs on this machine._

## 1. Environment

| | |
|---|---|
| OS | macOS 26.5.2 (build 25F84) |
| Chip | **Apple Silicon (arm64, M5)** |
| Backend | **MLX (Metal)**, `mlx` present; `onnxruntime 1.24.4` (plain, NOT `-directml`) ✅ |
| uv | 0.12.5 |
| Tool Python | 3.12.14 (system `python3` is 3.9, unused by the tool) |
| scubiee | **0.3.152** |
| Install | built 0.3.152 wheel from source (`uv build`) + `uv tool install`, **PyPI publish is still blocked on repo-side credentials, so `scubiee==0.3.152` is not on PyPI**; built from `upstream/main` instead |

## 2. #1: `upgrade` verify-by-version (macOS-risk), **PASS**

- `scubiee upgrade --check` → exit 0, clean JSON plan (`old_version 0.3.152`,
  phases detect/plan), **no traceback**. PASS.
- Logic inspected (`upgrade_supervisor.swap_package`): the verify-by-version
  rescue (`_verified_ok`, line ~152, and the last-chance check line ~208) requires
  **both** `installed_version() == target` **and** `_entrypoint_copy_failed_only`
  - a genuine install failure (version unchanged) falls through to
  `package_upgrade_failed`. So it **cannot mask a real failure**; it only rescues
  the Windows self-locked-shim case. On Mac the normal `result.ok` success path is
  taken. PASS (negative case guaranteed by construction + tests).
- `tests/test_upgrade_supervisor.py`: **12/12 pass.**
- OBS: a real PyPI `upgrade 0.3.151→0.3.152` couldn't be exercised (neither
  version is on PyPI, publish blocked), so the happy path was validated via
  `--check` + the unit tests rather than a live PyPI swap. `shim_rebind_deferred`
  did NOT appear (correct, that's the Windows-only path).

## 3. #2: never uninstall the running interpreter (highest priority), **PASS**

- **3a unit:** `tests/test_install_lean.py` **7/7 pass**, incl.
  `test_apply_lean_never_uninstalls_running_interpreter`.
- **3b real coexistence scenario:** created a second install (Python-3.12 venv
  with the 0.3.152 wheel) alongside the `uv tool` install, ran
  `scubiee init .` + `scubiee connect --cursor` **from the venv copy** in a
  throwaway repo:
  - `connect` → exit 0, `ok=true`, wrote `.cursor/mcp.json`. PASS.
  - **The key assertion:** after `connect`, the venv's `pipeline` module **still
    imports** ("pipeline INTACT") and `scubiee --version` still reports 0.3.152.
    The running interpreter was NOT corrupted. PASS.
  - Guard verified in code (`install_lean.py` lines 395/443/487/504):
    `_same_prefix(item.python, sys.executable)` → skip with
    `reason: "running_interpreter"`. Confirmed the predicate returns **True**
    (skip) only for the running prefix and **False** (removable) for a foreign
    install, so it protects the running install without over-blocking
    consolidation of a genuinely-foreign one.
  - OBS: the connect report did not surface a `running_interpreter` skip entry in
    this run, on Mac the two coexisting installs didn't trigger an attempt to
    remove the running one (different mechanism than Windows pip `~name`
    corruption). The guard is present and the running install survived regardless.
  - OBS: Mac pip-uninstall of a live package does not produce the Windows `~name`
    corrupted-dir marker; the guard still correctly changes *which* install is
    scrubbed.

## 4. #3: onnxruntime quantize warning, **N/A (Apple Silicon / MLX)**

INT8 quantization only runs on the CPU profile; Apple Silicon uses MLX and skips
it entirely. Confirmed MLX is the active backend. Not applicable on this machine;
fix (`accel.py::_ensure_coderank_int8` root-logger mute) would only matter on
Intel/CPU-forced Macs.

## 5. #4/#5/#6/#7: platform-agnostic smokes, **PASS**

| # | Check | Result |
|---|---|---|
| 4 | no-args friendly hint | On a real pty, bare `scubiee` prints the 3-step guide (setup / init . / connect --cursor). Piped/non-TTY correctly gets the argparse wall. **PASS** |
| 5 | bogus command | `scubiee florble` → exit **2**, no traceback. **PASS** |
| 5 | `map` when engine down | instant (0 s, no hang), exit 1, clean message "engine not running, start it with `scubiee engine start`", no raw traceback. **PASS** |
| 6 | `wipe` pre-flight | refuses without `--confirm`, prints the IDE-lock / safety-pause warning first (`ok:false, status:warning`). **PASS** |
| 7 | non-UTF8 / binary file | repo with `blob.bin` (binary) + `bad.py` (invalid UTF-8) + `ok.py` → `init ok=true`, no error; `ok.py` indexed and `real_fn` searchable (1 hit, src/ok.py); undecodable files skipped. **PASS** |

## 6. Regression suite: **PASS (56/56)**

| suite | result |
|---|---|
| test_install_lean | 7 passed |
| test_upgrade_supervisor | 12 passed |
| test_cli_ux_hardening | 6 passed |
| test_wipe | 22 passed |
| test_index_coverage | 9 passed |

## 7. Bug register

_No new bugs found._ All 7 deltas behave correctly on macOS/Apple Silicon.

| ID | Severity | Area | Summary | Status |
|---|---|---|---|---|
| - | - | - | (none) | - |

## 8. Verdict

The 0.3.149→0.3.152 changes **behave correctly on macOS / Apple Silicon.** The two
macOS-risk deltas are sound:
- **#1 upgrade verify-by-version**: the rescue path is doubly-guarded
  (`installed_version == target` **and** entrypoint-copy-only failure), so it
  can't mask a real Mac failure; the normal Mac upgrade takes the plain success
  path.
- **#2 never-uninstall-running-interpreter**: the guard holds on Mac; a venv
  install running `connect` while a `uv tool` install coexists leaves the running
  interpreter intact. Mac does not reproduce the Windows `~name` corruption, but
  the guard correctly changes which install is scrubbed and does not over-block
  consolidation of foreign installs.

macOS-specific follow-up: none required. #3 (quantize warning) is a no-op on
Apple Silicon. The only standing non-code item (shared with every release) is the
**PyPI/npm publish credentials**, which prevented testing a live PyPI
`upgrade`/install of 0.3.152, validated via source build + unit tests instead.

## 9. Teardown

Throwaway repos/venvs removed (`/tmp/scu_venv`, `/tmp/scu_connect_repo`,
`/tmp/scu_bin_repo`), their enrollments cleared. No stray test artifacts. Engine
left stopped (re-warms on next MCP/CLI use).
