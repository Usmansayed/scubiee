# Session Handoff: MacBook CLI Bug Hunt + 0.3.11 / 0.3.12

**Date:** September 2, 2026  
**Machine:** Apple Silicon MacBook (MLX ~63–112 t/s)  
**Repo:** `https://github.com/Usmansayed/new-context-engine.git`  
**Remote:** `upstream` → `new-context-engine`  
**Commits:** `f7e1d21` (0.3.11), `fe5b73e` (0.3.12)  
**PyPI:** [scubiee 0.3.12](https://pypi.org/project/scubiee/0.3.12/)  
**Prior handoff:** [session-summary-aug31-2026-macbook.md](./session-summary-aug31-2026-macbook.md)

---

## MacBook — start here

```bash
cd ~/path/to/new-context-engine
git pull upstream main

uv tool install --force scubiee==0.3.12 --index-url https://pypi.org/simple --refresh
export PATH="$HOME/.local/bin:$PATH"
scubiee --version   # expect 0.3.12

# Real CLI combination matrix (39 scenarios, isolated CTX_HOME)
mkdir -p /tmp/scubiee-tiny/.git && echo 'x=1' > /tmp/scubiee-tiny/app.py
python scripts/run_cli_combination_tests.py \
  --cli "$(which scubiee)" \
  --repo /tmp/scubiee-tiny \
  --json /tmp/cli_combo.json
```

**Do not set `CTX_HOME=/tmp/...` for normal use** — production CLI refuses polluted temp homes (exit 1). Combination tests use temp dirs under `/var/folders/...` via the runner, or set `CTX_ALLOW_TEST_HOME=1` for deliberate isolation.

---

## What this session was about

End-to-end **real `scubiee` CLI** testing across lifecycle, stop/resume, connect, wipe, and edge cases — not `python -m pipeline` imports. Goal: find user-facing bugs before release.

**Method:**
1. Built wheel from source and installed into a clean venv (not editable `.venv` only).
2. Ran expanded **39-scenario** combination matrix (`scripts/run_cli_combination_tests.py --cli`).
3. Manual CLI probes on default `~/.scubiee` + `$HOME` sandbox repos.
4. Fixed bugs, shipped **0.3.11** and **0.3.12**, published to PyPI.

---

## Releases shipped

| Version | Tag | Highlights |
|---------|-----|------------|
| **0.3.11** | `v0.3.11` | `activate` after `pause` un-pauses repo; CLI combination runner `--cli` + 17 new scenarios; MCP hot-reload test fix |
| **0.3.12** | `v0.3.12` | `status` honest for unmanaged repos; repo `wipe` requires `--confirm` + drops VectorDB; `turbo_quant` dequantize guard |

**Publish:** manual `twine upload` from maintainer machine (GitHub Actions publish workflow still fails on private-repo checkout).

```bash
uv build
TWINE_USERNAME=__token__ TWINE_PASSWORD="$(grep pipy_password .env | sed 's/.*= *//' | tr -d '\r')" \
  python -m twine upload dist/scubiee-*
git push upstream main && git tag vX.Y.Z && git push upstream vX.Y.Z
```

---

## Bugs found and fixed

### 0.3.11

| Bug | Fix |
|-----|-----|
| `scubiee activate .` after `pause` returned `ok:false`, `error:"paused"` | `activate_repo()` transitions `PAUSED → ACTIVE` (`repo_lifecycle.py`) |
| Combination runner marked `gate` as blocked while globally stopped (false FAIL) | Only flag blocked when exit ≠ 0; G13 expects `any` |

### 0.3.12

| Bug | Fix |
|-----|-----|
| `scubiee status` on never-initialized folder showed fake `store` / `collection` | Early return `{enrolled: false, state: "unmanaged"}` (`__main__.py`, `cli_ui.py`) |
| `scubiee wipe <repo>` ran without confirmation | `wipe()` requires `yes=True`; TTY prompt or `--confirm` (`wipe.py`, `__main__.py`) |
| Repo wipe left orphan VectorDB collections | `_drop_repo_vectordb_collections()` + legacy index cleanup (`wipe.py`) |
| `wipe` confirm-required sometimes exited 0 | Final exit path returns 2 when `confirm_required` |
| `turbo_quant` RuntimeWarning on 1-chunk repos (dequantize) | Re-normalize after inverse rotation; guard `n <= 0` |

### Known / open (not fixed in 0.3.12)

| Issue | Notes |
|-------|-------|
| `turbo_quant` warnings on **quantize** (line 146) during init of tiny repos | Dequantize fixed; quantize path may still warn on 1-chunk index |
| `CTX_HOME=/tmp/...` blocks most commands (by design) | `wipe` bypasses guard intentionally; use `CTX_ALLOW_TEST_HOME=1` for isolated CLI tests |
| GitHub Actions `publish` workflow | Checkout fails (`repository not found`) on private repo; use manual twine |
| `sync-now` while repo `paused` still succeeds | May be intentional (pause blocks `init`, not manual sync) |

---

## Real CLI test results (Sep 2 Mac)

### Combination matrix — **39/39 PASS** (~90s)

```bash
python scripts/run_cli_combination_tests.py \
  --cli /path/to/scubiee --repo /tmp/scubiee-tiny --json results.json
```

Groups: readonly (R1–R4), global stop (G1–G13), engine-only stop (E1–E7), connect (C1–C3), lifecycle (L1–L6), wipe (W1–W3), recovery (X1–X8), init combos (I1–I2), disconnect (D1).

### Connect + MCP merge — PASS

| Script | Result |
|--------|--------|
| `bash tests/_e2e_run_connect.sh` | C1–C4 dry-run OK |
| `python tests/_e2e_mcp_merge_experiment.py` | 13/13 tools |
| `bash tests/_e2e_mcp_merge_experiment.sh` | cursor, claude, codex, opencode OK |

### Bug-hunt script (new)

`tests/_cli_bughunt.sh` — edge cases (invalid args, pause/activate, never-index, global stop, symlink paths).  
Use `$HOME` sandbox, not `/tmp` CTX_HOME. Run:

```bash
SCUBIEE_BIN="$(which scubiee)" bash tests/_cli_bughunt.sh
```

### Post-0.3.12 verification

```bash
scubiee status ~/random-folder        # enrolled: false, state: unmanaged
scubiee wipe ~/sandbox                # confirm_required (exit 2)
scubiee wipe ~/sandbox --confirm      # ok; vectordb dropped
scubiee status ~/sandbox              # enrolled: false after wipe
```

---

## Files changed (handoff-relevant)

| Path | Purpose |
|------|---------|
| `packages/pipeline/repo_lifecycle.py` | activate after pause |
| `packages/pipeline/__main__.py` | status unmanaged; wipe confirm TTY + exit codes |
| `packages/pipeline/wipe.py` | repo confirm gate; vectordb + legacy index cleanup |
| `packages/pipeline/turbo_quant.py` | dequantize edge case |
| `packages/pipeline/cli_ui.py` | status summary for unmanaged |
| `scripts/run_cli_combination_tests.py` | `--cli`, expanded scenarios, blocked detection |
| `tests/_e2e_cli_combination_isolated.sh` | isolated CTX_HOME orchestrator |
| `tests/_cli_bughunt.sh` | CLI edge-case hunter |
| `tests/test_wipe.py` | `test_wipe_repo_requires_yes` |
| `tests/test_repo_lifecycle.py` | `test_status_unmanaged_returns_enrolled_false` |

---

## Pytest (focused)

```bash
uv run python -m pytest \
  tests/test_wipe.py \
  tests/test_repo_lifecycle.py::test_status_unmanaged_returns_enrolled_false \
  -q
# 20 passed (wipe suite + status test)
```

---

## Next session suggestions

1. Fix `turbo_quant` quantize warnings for 1-chunk repos (wrap `unit @ rotation` in `errstate` or skip TQ for N&lt;2).
2. Repair GitHub Actions publish workflow for private `new-context-engine` repo (or document manual-only publish).
3. Run destructive `bash tests/_e2e_run_cmds.sh` on Mac after `uv tool install scubiee==0.3.12` (uses real `~/.scubiee`).
4. Decide whether `sync-now` should respect repo `paused` state.

---

## Quick reference

| Command | Expected (0.3.12) |
|---------|-------------------|
| `scubiee status <unmanaged>` | `enrolled: false` |
| `scubiee wipe .` | `confirm_required`, exit 2 |
| `scubiee wipe . --confirm` | Removes enrollment + vectordb for repo |
| `scubiee pause .` then `activate .` | `state: active` |
| `scubiee stop -y` then `init .` | Blocked until `resume` |
