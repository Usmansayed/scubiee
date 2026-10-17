# Fresh-user simulation — scubiee 0.3.151 (Windows, venv + PyPI)

_A from-scratch walkthrough: isolated venv, `pip install -U scubiee` from PyPI,
then the README quick-start (`setup → init → connect → everyday commands`) on a
realistic sample repo. Goal: experience exactly what a brand-new Windows user
feels, and surface any inconvenience. Run against the published 0.3.151 wheel._

## TL;DR

The core engine is genuinely good — install, setup, indexing, and semantic
search all work and the search quality is strong. **One serious first-run
pitfall exists**: on Windows, when a pip/venv install **coexists with a uv-tool
install**, `scubiee connect` (and setup's engine step) uninstalls the venv copy
of its own `pipeline` package *mid-command*, leaving it broken with a cryptic
`No module named 'pipeline.connect_state'`. A user with only a single install
does **not** hit this. Plus a few cosmetic rough edges.

## What worked well

- **Install** — `pip install -U scubiee` pulled 0.3.151 and all deps cleanly.
- **setup** — detected hardware, chose the `dml` (DirectML) profile, downloaded/
  warmed the embedding model, calibrated speed, ended with a clear
  `Ready (dml). Next: scubiee init .` It also printed a helpful
  `note: another scubiee install found at ...` (nice multi-install awareness).
- **init** — indexed the 5-file sample app into 13 chunks (768-dim, INT8/turboquant,
  4× compression), Merkle freshness `clean`, server `warm_state: ready`. Fast.
- **search** — query _"hash and verify a user password"_ returned, in order:
  `hash_password` (core/auth.py), `login_handler` (api/routes.py), the JS
  `postLogin` (web/app.js), then `get_user` (core/db.py). Correct ranking across
  files **and** languages via fused `bm25+dense+graph`. The semantic
  understanding is the real deal.
- **connect** (once unblocked) — wrote `.cursor/mcp.json`, `.cursor/rules/scubiee.mdc`,
  `.cursor/permissions.json`, and `AGENTS.md` with the GATE line, enrolled the
  repo, registered the logon supervisor. `ok: true`, complete and correct.

## Serious finding — connect corrupts a coexisting pip install

**Severity: HIGH (conditional).** Triggers only when a pip/venv install and a
uv-tool install of scubiee exist on the same machine.

### Symptom

`scubiee connect --cursor` fails with:

```
[scubiee] connect failed: No module named 'pipeline.connect_state'
```

After that, even `scubiee version` fails with `No module named 'pipeline'`. On
disk, the `pipeline` package directory has been renamed to `~ipeline` (pip's
interrupted-operation marker) and the `scubiee` dist-info is gone.

### Root cause

`pipeline/install_lean.py` → `apply_lean()` → `uninstall_pip_copies()` is the
"consolidate to one install" routine: it treats the **uv-tool** copy as the
keeper and **pip-uninstalls every non-uv-tool copy**. When invoked from a pip
venv (which `connect`/`setup` do), it uninstalls the *currently running
process's own* `pipeline` package. On Windows the files are locked by the live
interpreter, so pip leaves the package half-renamed (`~ipeline`) and cannot
restore it. The command then tries to import `pipeline.connect_state` and dies.

The daemon that was already started keeps running (its code is in memory), which
masks the breakage until the next fresh CLI call.

### Scope / who hits it

- **Hit:** users who have both `pip install scubiee` (in a venv or global) *and*
  `uv tool install scubiee`. The guard detects the other install (the
  `note: another scubiee install found` line) and scrubs the pip copy.
- **Not hit:** a clean user with a **single** install (just `pip install
  scubiee`, or just `uv tool install scubiee`). `choose_keeper` picks the sole
  install and nothing is uninstalled. This is the common first-run case, so the
  default README path is safe — but the failure mode is severe when it happens.

### Workaround (confirmed)

Setting `SCUBIEE_KEEP_OTHER_INSTALLS=1` fully prevents the corruption — with it,
`connect` completed successfully end-to-end. Recovery after corruption:
`pip install --force-reinstall --no-deps scubiee==<version>`.

### Recommended fixes

1. **Never uninstall the install that the current process is running from.** In
   `apply_lean`/`uninstall_pip_copies`, skip any candidate whose prefix matches
   `sys.prefix` (and ideally whose files are import-locked). This alone prevents
   self-corruption.
2. If consolidation is still wanted, do it by **re-exec into the keeper first**,
   then scrub — never scrub the live interpreter's own package.
3. Replace the user-facing error: `No module named 'pipeline.connect_state'`
   should become something like _"scubiee was consolidating multiple installs
   and needs a restart — re-run your command"_ with the recovery line.

## Cosmetic rough edges (low severity)

1. **~10s silent-looking "Retrying GPU/CPU engine" stall** during `setup`, caused
   by a plain `pip install` pulling in **both** `onnxruntime` and
   `onnxruntime-directml` (the clobber scenario the DML override avoids). Setup
   recovered and DML worked, but the stall looks like a hang to a newcomer. The
   README's DirectML-override note would prevent it — consider surfacing that
   note more prominently, or auto-removing the generic `onnxruntime` during setup.
2. **Raw library warning leaks into the clean progress UI:**
   `WARNING:root:Please consider to run pre-processing before quantization...`
   from onnxruntime appears mid-progress-bar. Should be suppressed/captured.
3. **`scubiee` with no args** dumps a dense one-line wall of ~35 subcommand names
   then `error: the following arguments are required: cmd`. A friendlier
   "run `scubiee setup` to get started" would land better for a first-timer.
4. **First search is cold (~8s)** while FastEmbed loads (3s of it); warm queries
   are fast. Worth a one-line "warming up…" hint on the first query.

## Verified-good error handling

- Bad subcommand → exit 2 + usage, no traceback.
- `init` on a nonexistent path → clean `Failed: not a directory`, no traceback.
- Unquoted multi-word `search`/`map` queries → argparse "unrecognized arguments"
  (standard shell quoting; quoting the query works). Not a scubiee bug, but a
  predictable newcomer stumble — docs already show quoted queries.
- `setup` with a `/temp/` CTX_HOME → politely refused (safety guard).

## Environment restored after the sim

Killed all sim processes, removed the venv/home/sample repo, and **restored the
real install's logon autostart** (the sim's `connect` had overwritten the HKCU
`Run\ContextEngineSupervisor` key — re-pointed it at the real uv-tool install +
`~/.scubiee`). Connect state back to `['kiro']`.
