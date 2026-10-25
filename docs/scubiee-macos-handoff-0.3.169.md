# Scubiee macOS Handoff: v0.3.169 (pre-production checks, 0.3.162 → 0.3.169)

**For:** the MacBook (Apple Silicon, MLX backend, `uv tool install scubiee`,
tool venv under `~/.local/share/uv/tools/scubiee`).

**Status:** 0.3.163-0.3.169 were built and validated on Windows only. None of
them has run on macOS. Run every section below before calling 0.3.169
production-ready on Mac, and write findings to
`docs/scubiee-macos-findings-0.3.169.md`, using the M-number register from
`docs/scubiee-macos-handoff-0.3.162.md` (continue at M28).

---

## 1. What changed since the last Mac pass (0.3.162)

| Version | Commit | Change | Mac risk |
|---|---|---|---|
| 0.3.163 | c7a403b, b711eb6 | Dead-pid detection (Windows `GetExitCodeProcess`); index walk prunes Scubiee-excluded dirs (10.5 s → 3.0 s); admission skips registry rewrite < 60 s; embed-cache replay only unknown keys; warm phase publishes `dense` when the session loads; engine-down recovery uses `ensure_daemon(open_wait=False)` | Shared walk/warm/recovery code. Confirm MLX still reaches `dense` and the M27 zombie path still works |
| 0.3.164 | 025bc91 | conftest puts absolute `packages/` on `PYTHONPATH` for spawned children; polytrace stays in the seed's faction | Test harness only; full suite should be cleaner |
| 0.3.165 | a24bfcf | `engine start`/`setup`/`serve` honour `CTX_ENGINE_URL` port; CLI `map` starts or attaches the engine; `doctor` reports `publication_updating` mid-sync | LaunchAgent / custom port |
| 0.3.166 | ec31e13 | `wipe --all --keep-package` no longer deletes the tool (unlock runs only when removing the package) | Shared wipe code |
| 0.3.167 | 1c8d3ef | First `map find` after a worker (re)start no longer races `_warm` (~3 s → ~0.35 s); engine opener is plain HTTP | Re-measure first-call latency on Mac |
| 0.3.168 | c3bd35a | Ignore hardening: venv/conda envs by `pyvenv.cfg`/`conda-meta`, `venv*` names, minified/binary/one-line-blob files, exact-case check for `vendor`/`dist`/`build`/`out`/`target`/`coverage`… against the **on-disk** name, `build`/`out` with `__init__.py` kept, root `.gitignore` applied to sync + merkle scan, startup prune of now-ignored chunks | **High: APFS is case-insensitive by default**, same as NTFS. The exact-case logic must behave on Mac |
| 0.3.169 | 97b5675 | `scubiee upgrade` always rewrites MCP config + GATE rules for connected tools; after a package swap the rewrite runs in a **fresh interpreter** (`sys.executable -c …`, `PYTHONPATH` = installed package parent); MCP writers skip identical content | **High:** first real upgrade on Mac. Interpreter path is `…/uv/tools/scubiee/bin/python` |

### Windows evidence for 0.3.169 (for comparison)

- Real `scubiee upgrade` 0.3.168.1 → 0.3.169: all phases ok, rebind
  `fresh_process: true`, planted outdated `scubiee.mdc` restored byte-identical,
  planted `mcp.json` drift repaired. Health: installed and daemon both 0.3.169.
- No-op `scubiee upgrade` on 0.3.169 (9 s): rules and `AGENTS.md` untouched.
  `mcp.json` changed only in `CTX_SCUBIEE_BUILD` (intentional hot-reload stamp).
- Lane A run 1 failed `map_second` 1,182 ms (`LOCATE_SLA`, 1 s budget) right
  after the upgrade. Rerun: 15/15 ok (map_first 500 ms, map_second 542 ms,
  post_idle_map 456 ms). `warm_contract` failed 0 (first map 899 ms, after idle
  270 ms). `ship_check` ok, 0 errors.

---

## 2. Setup

```bash
cd /path/to/context-engine && git pull          # main must be at or past 97b5675
scubiee --version                                # note the starting version
cat ~/.scubiee/connected_tools.json              # must list "cursor" for §4
TOOL_PY=$HOME/.local/share/uv/tools/scubiee/bin/python
```

In-repo pytest needs `PYTHONPATH=packages`. Installed-tool scripts must **not**
set it.

---

## 3. Unit / integration tests (from the checkout)

```bash
PYTHONPATH=packages python -m pytest -q \
  tests/test_ignore_hardening.py tests/test_corpus_ghosts.py \
  tests/test_upgrade_rebind_fresh.py tests/test_mcp_hot_reload_reliability.py \
  tests/test_upgrade_scenarios.py tests/test_upgrade_cli_integration.py \
  tests/test_map_warm_race.py tests/test_engine_down_recovery.py \
  tests/test_wipe.py tests/test_lifecycle_runtime.py
PYTHONPATH=packages python -m pytest -q tests     # full suite
```

**Pass bar:** the targeted set is all green. For the full suite, list every
failure with its reason. On Windows, 16 failures were all embedder/model
tests caused by a broken local `opentelemetry` package. Compare: any failure
outside embedder/model tests is a finding.

`tests/test_upgrade_rebind_fresh.py::test_fresh_rebind_writes_current_templates_not_stale_in_memory`
spawns a real interpreter. If it fails on Mac, capture `fresh_process_error`.

---

## 4. Real upgrade test (0.3.169 headline; must pass)

An upgrade runs through the **installed** version's code, so upgrading from
PyPI 0.3.168 would exercise the old rewrite. Install this code labelled
`0.3.168.1` (valid, between 0.3.168 and 0.3.169), plant drift, then upgrade
to PyPI 0.3.169.

```bash
sed -i '' 's/^version = "0.3.169"/version = "0.3.168.1"/' pyproject.toml
uv build --wheel --out-dir /tmp/scubiee_168_1 && git checkout pyproject.toml
scubiee engine stop
uv tool install --force --reinstall /tmp/scubiee_168_1/scubiee-0.3.168.1-py3-none-any.whl
scubiee --version                                  # 0.3.168.1

mkdir -p /tmp/stale_bak && cp .cursor/rules/scubiee.mdc .cursor/mcp.json /tmp/stale_bak/
echo "OUTDATED GATE BODY" > .cursor/rules/scubiee.mdc
python3 - <<'EOF'
import json; p=".cursor/mcp.json"; d=json.load(open(p))
e=d["mcpServers"]["scubiee"].setdefault("env",{}); e.pop("CTX_TRACE_PARALLEL",None); e["CTX_STALE_KEY"]="old"
open(p,"w").write(json.dumps(d,indent=2)+"\n")
EOF

scubiee upgrade > /tmp/upgrade_169.log 2>&1; echo "exit=$?"
python3 - <<'EOF'
import json
log=open("/tmp/upgrade_169.log").read(); dec=json.JSONDecoder(); rep={}; i=log.find("{")
while i>=0:
    try:
        o,_=dec.raw_decode(log,i)
        if isinstance(o,dict) and "phases" in o: rep=o; break
    except ValueError: pass
    i=log.find("{",i+1)
rb=rep.get("rebind",{}); h=rep.get("health",{})
print("ok",rep.get("ok"),"old",rep.get("old_version"),"new",rep.get("new_version"))
print("rebind ok",rb.get("ok"),"fresh_process",rb.get("fresh_process"),"err",rb.get("fresh_process_error"))
print("health",h.get("ok"),h.get("installed_version"),h.get("daemon_version"))
m=open(".cursor/rules/scubiee.mdc").read(); print("mdc restored", m==open("/tmp/stale_bak/scubiee.mdc").read())
e=json.load(open(".cursor/mcp.json"))["mcpServers"]["scubiee"]["env"]
print("mcp fixed", "CTX_STALE_KEY" not in e and e.get("CTX_TRACE_PARALLEL")=="1")
EOF
```

**Pass bar:** `ok True`, new `0.3.169`, `fresh_process True` with no error,
health installed = daemon = 0.3.169, `mdc restored True`, `mcp fixed True`.
Also confirm the LaunchAgent engine came back (`curl -s 127.0.0.1:8765/health`)
and Cursor's Scubiee MCP reconnects (reload the MCP server once).

Then the no-op check:

```bash
stat -f '%m %N' .cursor/rules/scubiee.mdc AGENTS.md .cursor/mcp.json
scubiee upgrade > /tmp/upgrade_noop.log 2>&1; echo "exit=$?"
stat -f '%m %N' .cursor/rules/scubiee.mdc AGENTS.md .cursor/mcp.json
```

**Pass bar:** exit 0. `scubiee.mdc` and `AGENTS.md` mtimes unchanged.
`mcp.json` may change **only** in `CTX_SCUBIEE_BUILD`.

---

## 5. Ignore hardening on a case-insensitive volume (0.3.168)

Use a scratch git repo enrolled with `scubiee init .` (not this repo).

| Create | Expected |
|---|---|
| `Build/Build.cs` (capital B) | **indexed**: on-disk name is `Build`, not `build` |
| `build/out.js` | ignored |
| `src/build/__init__.py` + `src/build/core.py` | **indexed**: Python package exemption |
| `Vendor/lib.go` vs `vendor/lib.go` | `Vendor` indexed, `vendor` ignored |
| `myenv/pyvenv.cfg` + `myenv/lib/x.py` | ignored (venv by marker, any name) |
| `venv311/x.py`, `.venv-old/x.py` | ignored |
| `app.min.js`, a 60 KB one-line JSON blob | ignored |
| `secret_build/` listed in root `.gitignore` | ignored, also after `touch` + save (sync path) |
| `normal.py` | indexed |

Check with `scubiee map --config find` on a unique symbol from each file, or
the engine's file list. Then delete `build/out.js` and edit `normal.py`:
deletion and change both sync. Finally add `node_modules/x.js` to an
already-indexed repo, restart the engine, and confirm the startup prune logs
`ignored prune path(s)` and the file is gone.

**Pass bar:** every row matches. Any normal source file dropped is a P0 false
positive.

---

## 6. Live battery on the upgraded install (required before production)

```bash
cd /path/to/context-engine
"$TOOL_PY" scripts/mcp_host_sim.py --lane a --live --settle-s 35 --out-dir /tmp/hostsim_169
"$TOOL_PY" scripts/warm_contract_acceptance.py
"$TOOL_PY" scripts/scubiee_mcp_ship_check.py
git checkout docs/superpowers/plans/2026-09-06-mcp-ship-check.json   # ship_check rewrites it
```

**Pass bar:** Lane A 15/15 `ok=True`. `map_second` must be under 1 s; if run 1
misses only on that, rerun once and report both runs. `warm_contract`
`failed: 0`; record `first_map_after_ready` and `map_after_idle_ms`.
`ship_check` errors `[]`, preview shows `phase=dense` and `version=0.3.169`.
Report all phase timings in a table like §3 of the 0.3.162 handoff.

Lane A `clean_slate` re-inits the repo and can delete init-generated `.kiro/*`.
Run `scubiee init .` afterwards. Never commit init-generated `AGENTS.md`,
`.copilot/*` or `.kiro/*` changes.

---

## 7. Targeted regressions for 0.3.163-0.3.167

1. **Engine-down recovery (M27 + 0.3.163):** with Cursor attached,
   `kill -9 $(lsof -ti tcp:8765 -sTCP:LISTEN)`, then one MCP `map find`. It
   should answer, and `/health` should show a new pid with `warm_state` reaching
   dense on MLX.
2. **First find after worker restart (0.3.167):** reload Scubiee MCP in Cursor
   and immediately run `map find`. Target < 1 s (Windows: 344-386 ms).
3. **Custom port (0.3.165):** `CTX_ENGINE_URL=http://127.0.0.1:8799 scubiee engine start`
   listens on 8799, and `scubiee map --config find …` with the same env works.
   Restore the default afterwards.
4. **doctor mid-sync (0.3.165):** run `scubiee doctor` while a large save
   syncs. Expect `publication_updating`, not "corrupt - rebuild index".
5. **wipe keep-package (0.3.166):** `scubiee wipe --all --keep-package`, then
   `scubiee --version` still works. Re-run `setup`, `connect --cursor` and
   `init .` afterwards.

---

## 8. Go / no-go

Production-ready on Mac only if §3 targeted tests, §4, §5 and §6 all pass and
§7 has no high-severity finding. Report measured timings and ok flags for §4
and §6, not just "passed".

### Known, not blockers

- Full-suite embedder/model test failures that come from the local Python env.
- Lane A `map_second` margin is thin (Windows 542-1,182 ms across runs).
- Template changes inside 0.3.169 itself are only guaranteed to apply from the
  **next** upgrade, or after `scubiee connect --cursor`, because the upgrade
  into 0.3.169 runs the previous version's code. The §4 test avoids this by
  installing 0.3.168.1 first.
