# Scubiee macOS Handoff — v0.3.152 (delta since the 0.3.145 pass)

**You are:** an autonomous coding agent on a **macOS** machine (Apple Silicon
preferred; note Intel if that's what you have) with a terminal and, ideally, the
`@scubiee/*` MCP tools connected.

**Your job:** macOS already ran the big reliability/perf battery for 0.3.145
(embedder/MLX, cold-start, health-under-load, graph-catchup, launchd, sync lanes,
MCP/HTTP/CLI parity). **Do not repeat all of that.** This handoff covers only the
**new changes landed on Windows in 0.3.149 → 0.3.152** that macOS has NOT seen.
Validate each on Mac, fix any macOS-specific breakage, and write a short findings
doc. If a 0.3.145 area was already GREEN and none of the deltas below touch it,
you can skip re-testing it.

**Authority:** yes to install, run, test, edit code, rebuild, commit on a branch.
Do **not** push or open PRs without being asked. No destructive commands
(`wipe`/`remove`/`halt`/force-delete) except in the teardown step on throwaway data.

**Deliverable:** `docs/scubiee-macos-findings-0.3.152.md` (template in §7).

---

## 0. What changed since 0.3.145 — the only things to test here

All of these were found and fixed on Windows during the production-hardening and
fresh-user passes. Each is called out as **platform-agnostic** (should behave the
same on Mac — just confirm) or **macOS-risk** (the code path differs on Mac and
genuinely needs validation).

| # | Version | Change | Mac risk? |
|---|---|---|---|
| 1 | 0.3.151 | **`upgrade` verify-by-version** — `scubiee upgrade` no longer reports `package_upgrade_failed` when the package actually swapped but the CLI shim couldn't be rewritten (Windows self-locked `.exe`). Success is now judged by installed version, not just installer exit code. | **macOS-risk** — the shim-lock is Windows-specific, but the new success-detection path runs on all platforms. Confirm Mac upgrade still reports correctly and the new logic doesn't mis-classify a Mac upgrade. |
| 2 | 0.3.152 | **Never uninstall the running interpreter** — `install_lean.apply_lean()` / `uninstall_pip_copies()` now skip the install whose prefix == `sys.executable`. On Windows, scrubbing the live pip copy mid-command corrupted it (`pipeline` → `~ipeline`). | **macOS-risk** — the install-consolidation path is cross-platform; the exact filesystem-lock corruption is Windows-specific, but the guard logic must be correct on Mac (and must not leave Mac unable to consolidate a genuinely-foreign install). |
| 3 | 0.3.152 | **Silence onnxruntime quantize warning** — root logger muted around `quantize_dynamic` so `WARNING:root:Please consider to run pre-processing before quantization` no longer leaks into the setup UI. | **macOS-risk (Intel/CPU only)** — INT8 quantization only runs on the **CPU** profile. On Apple Silicon (MLX) it's skipped entirely, so this only matters on **Intel Macs / CPU-forced** setups. |
| 4 | 0.3.152 | **Friendly no-args hint** — bare `scubiee` on a TTY prints a 3-step getting-started guide instead of the dense argparse usage wall. Scripts/pipes still get the argparse error. | platform-agnostic |
| 5 | 0.3.150 | **CLI traceback net + `map` engine-down handling** — top-level try/except in `main()` so no command dumps a raw Python traceback; `cmd_map` does a fast `healthy()` pre-check when the engine is down (no exit-0-on-failure, no raw error leak, no hang). | platform-agnostic |
| 6 | 0.3.150 | **`wipe` pre-flight + `connect_state` guard** — `wipe` warns about IDE locks *before* uninstalling; `uninstall_tool` survives a missing `connect_state` module via a no-op fallback. | platform-agnostic |
| 7 | 0.3.149 | **Non-UTF8 / binary files no longer abort indexing** — the indexer skips undecodable files instead of failing the whole index. | platform-agnostic (verify a Mac repo with a binary/non-UTF8 file indexes cleanly) |

Nothing in 0.3.149–0.3.152 changed the embedder, warm sequence, graph lane, or
launchd lifecycle. If those were GREEN in your 0.3.145 findings, they stay GREEN —
only re-smoke them if a delta below surprises you.

Reference: `docs/scubiee-fresh-user-sim-0.3.151.md` (the Windows fresh-user run
that surfaced #2/#3/#4), `docs/scubiee-cli-matrix-results.md` (the upgrade finding
behind #1), `docs/scubiee-cli-ux-findings.md` (#5).

---

## 1. Environment capture + install 0.3.152

```bash
sw_vers; uname -m; python3 --version; uv --version
scubiee engine stop 2>/dev/null || true
uv tool install --force --refresh "scubiee==0.3.152"   # from PyPI (published)
scubiee --version        # expect 0.3.152
```

> **Do NOT use `packaging/uv-overrides-win-dml.txt` on macOS** — it strips
> `onnxruntime`, which Mac needs. That override is Windows-only.

- **[ ] PASS/FAIL** installed version is 0.3.152.
- **[ ] OBS** which onnxruntime variant installed — on Mac it must be plain
  `onnxruntime` (NOT `-directml`). Confirm `mlx` present on Apple Silicon.

---

## 2. #1 — `upgrade` verify-by-version (macOS-risk)

The fix changed how `swap_package` decides success: it now also accepts the case
where the installer exits non-zero **but the installed version equals the target**
(the shim-only failure), returning `shim_rebind_deferred`. On Mac there's no
self-locked-`.exe`, so a normal upgrade should just succeed the normal way — the
point is to confirm the new logic didn't regress the Mac happy path.

```bash
scubiee upgrade --check          # should exit 0, show a clean plan
# If a newer version exists, do a real upgrade; else simulate a downgrade→upgrade:
uv tool install --force "scubiee==0.3.151"
scubiee upgrade                  # 0.3.151 → 0.3.152
echo "exit=$?"                   # expect 0
scubiee --version                # expect 0.3.152
```

- **[ ] PASS/FAIL** `upgrade --check` exits 0, no traceback.
- **[ ] PASS/FAIL** a real Mac upgrade exits 0 and ends on the target version with
  a clean "Upgraded X → Y" (NOT a false `package_upgrade_failed`).
- **[ ] PASS/FAIL (negative)** if you can force a genuinely failed swap (e.g. point
  at a nonexistent version), it still reports failure — the verify-by-version path
  must not mask real failures. Inspect: `swap_package` in
  `packages/pipeline/upgrade_supervisor.py` (look for `shim_rebind_deferred` and
  the last-chance `installed_version() == target` check).
- **[ ] OBS** does the Mac upgrade ever print the `shim_rebind_deferred` note? It
  shouldn't normally (that's the Windows shim case) — if it does on Mac, note why.

---

## 3. #2 — never uninstall the running interpreter (macOS-risk, highest priority)

This is the one that most needs Mac eyes. The Windows repro: a pip/venv install
coexisting with a `uv tool` install, then `scubiee connect` (or `setup`) ran the
install-consolidation, which pip-uninstalled the **running** pip copy mid-command
and corrupted it. The fix skips any candidate whose prefix == `sys.executable`.

### 3a. The guard itself (unit-level, fast)
```bash
cd /path/to/context-engine
PYTHONPATH=packages python3 -m pytest tests/test_install_lean.py -q
```
- **[ ] PASS/FAIL** all `test_install_lean` pass, including
  `test_apply_lean_never_uninstalls_running_interpreter`.

### 3b. The real coexistence scenario on Mac (the important one)
Reproduce the two-install situation and confirm `connect` does NOT break the
running install:
```bash
# 1) uv tool install (one install)
uv tool install --force "scubiee==0.3.152"
# 2) ALSO create a pip/venv install of the same version
python3 -m venv /tmp/scu_venv
/tmp/scu_venv/bin/python -m pip install "scubiee==0.3.152"
# 3) run connect FROM THE VENV copy, inside a throwaway repo
mkdir -p /tmp/scu_connect_repo && cd /tmp/scu_connect_repo && git init -q
/tmp/scu_venv/bin/scubiee init .
/tmp/scu_venv/bin/scubiee connect --cursor
echo "exit=$?"
# 4) the venv's own package must still import afterwards:
/tmp/scu_venv/bin/python -c "import pipeline.connect_state; print('pipeline intact')"
/tmp/scu_venv/bin/scubiee --version
```
- **[ ] PASS/FAIL** after `connect`, the venv's `pipeline` still imports and
  `scubiee --version` works (NOT `No module named 'pipeline'`).
- **[ ] PASS/FAIL** `connect` actually wrote `.cursor/mcp.json` + rules + enrolled
  the repo (`ok: true`).
- **[ ] OBS** check the connect report's `removed` list — the running interpreter
  should appear as `{"skipped": true, "reason": "running_interpreter"}`.
- **[ ] OBS** does Mac even leave a corrupted dir on uninstall (the `~name` marker
  is a Windows pip behavior)? Likely not — note whether Mac pip uninstall of a
  live package corrupts at all, or just no-ops. Either way the guard should hold.

> Why this matters even if Mac doesn't corrupt: the guard changes *which* install
> gets scrubbed. Confirm Mac still consolidates a genuinely foreign/older install
> (different prefix) — i.e. the guard didn't over-block. Add a foreign older pip
> copy and confirm `apply_lean` still removes it while sparing the running one.

### 3c. Teardown for 3b
```bash
/tmp/scu_venv/bin/scubiee remove /tmp/scu_connect_repo 2>/dev/null || true
rm -rf /tmp/scu_venv /tmp/scu_connect_repo
# Re-assert your primary install + connect state afterward.
```

---

## 4. #3 — onnxruntime quantize warning (Intel/CPU Macs only)

Only runs on the **CPU** profile (Apple Silicon/MLX skips INT8 entirely). If you're
on Apple Silicon, note this as **N/A (MLX path skips quantization)** and move on.
On Intel / CPU-forced:
```bash
CTX_EMBED_BACKEND=cpu scubiee setup --repair 2>&1 | tee /tmp/scu_setup.log
grep -i "pre-processing before quantization" /tmp/scu_setup.log && echo "LEAKED (FAIL)" || echo "clean (PASS)"
```
- **[ ] PASS/FAIL/N-A** the `WARNING:root:...pre-processing...` line must NOT appear
  in setup output. (Fix lives in `accel.py::_ensure_coderank_int8`.)

---

## 5. #4/#5/#6/#7 — platform-agnostic quick smokes

These should just work on Mac; confirm with a few commands.

```bash
# #4 no-args hint (run in an interactive shell / TTY)
scubiee                       # expect a 3-step getting-started guide, not a usage wall

# #5 traceback net + map-when-down
scubiee engine stop
scubiee florble               # bogus cmd → clean exit 2, NO python traceback
scubiee map "where is login" --config find   # engine down → clean message, no hang, no raw error
scubiee engine start

# #6 wipe pre-flight (DO NOT confirm — just observe the warning path)
scubiee wipe                  # must refuse without --confirm and warn about IDE locks first

# #7 non-UTF8 / binary file doesn't abort indexing
mkdir -p /tmp/scu_bin_repo/src && cd /tmp/scu_bin_repo && git init -q
printf '\xff\xfe\x00\x01 binary junk' > src/blob.bin
echo 'def real_fn(): return 1' > src/ok.py
scubiee init .
scubiee search "real_fn" .    # expect ok.py indexed; blob.bin skipped, no crash
```
- **[ ] PASS/FAIL** no-args shows the friendly hint on a TTY.
- **[ ] PASS/FAIL** bogus command → exit 2, no traceback; `map` with engine down →
  clean, no hang, no raw `RuntimeError`/stack.
- **[ ] PASS/FAIL** `wipe` refuses without `--confirm` and shows the IDE-lock
  warning first.
- **[ ] PASS/FAIL** the binary/non-UTF8 file is skipped and indexing still
  completes; `real_fn` is searchable.
- Teardown: `rm -rf /tmp/scu_bin_repo` (+ `scubiee remove` it first).

---

## 6. Regression suite

```bash
cd /path/to/context-engine
PYTHONPATH=packages python3 -m pytest tests/test_install_lean.py \
  tests/test_upgrade_supervisor.py tests/test_cli_ux_hardening.py \
  tests/test_wipe.py tests/test_index_coverage.py -q
```
- **[ ] PASS/FAIL** these pass (note any that fail only because your test python
  lacks mlx/fastembed — env-only, not a real regression).

---

## 7. Deliverable — `docs/scubiee-macos-findings-0.3.152.md`

Keep it tight — this is a delta pass, not a full battery. Include:
1. **Environment**: macOS version, chip, Apple Silicon vs Intel, backend, install
   method, scubiee version.
2. **Per-delta results** (§2–§6): PASS/FAIL/OBS/N-A with the actual output. Lead
   with **§3 (never-uninstall-running-interpreter)** — the highest-risk delta — and
   **§2 (upgrade verify-by-version)**.
3. **Bug register** (table): ID, severity, area, summary, root cause, fix
   (commit SHA if fixed), status. Do not push.
4. **Verdict**: do the 0.3.149→0.3.152 changes behave correctly on macOS? Any
   macOS-specific follow-up (e.g. does Mac even need the running-interpreter guard,
   or a Mac-specific install-consolidation nuance)?

### Priorities if short on time
1. **§3 running-interpreter guard** — the real coexistence scenario (3b).
2. **§2 upgrade verify-by-version** — Mac happy path + negative case.
3. **§5 quick smokes** (#4/#5/#6/#7).
4. **§4 quantize warning** — only if Intel/CPU.

---

## 8. Teardown
```bash
rm -rf /tmp/scu_venv /tmp/scu_connect_repo /tmp/scu_bin_repo /tmp/scu_setup.log
# unenroll any throwaway repos first with `scubiee remove <path>`
git status   # no stray test artifacts committed
```
Re-assert your real install + connect state, and leave the engine healthy+warm or
cleanly stopped — note which.

---

## Appendix — key facts
- **Version:** 0.3.152 (on PyPI + `origin/main`). **Engine:** `127.0.0.1:8765`.
- **Shipped MCP tools:** `map` (config `find`|`focus`), `gate`, `status`.
- **Mac dense backend:** MLX (Metal) on Apple Silicon; CoreML/CPU on Intel.
  Windows = DirectML.
- **Fixes in this delta live in:** `install_lean.py` (running-interpreter guard),
  `upgrade_supervisor.py` (`swap_package` verify-by-version), `accel.py`
  (`_ensure_coderank_int8` warning mute), `__main__.py` (no-args hint + `main()`
  traceback net + `cmd_map` healthy() pre-check), `wipe.py` / `connect_state`
  guard, indexer non-UTF8 skip.
- **Env knobs relevant here:** `CTX_EMBED_BACKEND` (`mlx`/`fastembed`/`cpu`/
  `coreml`), `SCUBIEE_KEEP_OTHER_INSTALLS=1` (skips install-consolidation — the
  explicit escape hatch for the §3 scenario). In-repo runs need
  `PYTHONPATH=packages`; installed-tool runs must NOT set it.
- **DO NOT** use `packaging/uv-overrides-win-dml.txt` on macOS (Windows-only).
