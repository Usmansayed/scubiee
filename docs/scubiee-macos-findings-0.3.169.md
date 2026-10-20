# Scubiee 0.3.169 — macOS findings (pre-production)

Run against `docs/scubiee-macos-handoff-0.3.169.md` on branch
`macos-validate-0.3.169` (from `upstream/main` 3a84d80).

**Verdict: GO for 0.3.169 on macOS.** §3, §4, §5 and §6 all pass, and §7 has
no high-severity finding. This pass found five bugs (M28–M32), all medium or
low. Each is fixed on this branch with regression tests and verified live.
None blocks 0.3.169; they belong in the next release.

## 1. Environment

| | |
|---|---|
| OS | macOS 26.5.2 (25F84), APFS (case-insensitive) |
| Chip | Apple M5 (arm64) |
| Backend | MLX (Metal), setup calibration ~85 t/s |
| Python | tool venv 3.11.16 (uv-managed) |
| uv | 0.12.5 |
| Install | Start: 0.3.162. §4: built 0.3.168.1 from main, then a real `scubiee upgrade` to PyPI 0.3.169. §5–§7: PyPI 0.3.169. Fix verification: wheel built from this branch |
| Unit tests | separate venv (uv, Python 3.11, `pip install -e . pytest`), `PYTHONPATH=packages` |

---

## 2. §3 Unit / integration tests

- **Targeted set:** 1 failure on stock main,
  `test_corpus_ghosts.py::test_mark_dirty_prune_bypasses_filter_but_not_outside_paths`.
  This is a real product bug on POSIX (M28). After the fix: **149 passed**,
  4 deselected.
- **Full suite** (stock main + M28 fix): **2,090 passed, 0 failed**, 25 skipped,
  13 deselected, 9 min 50 s. None of the Windows embedder/opentelemetry
  failures show up here.
- **Full suite** with all three fixes: **2,098 passed, 0 failed**, 25 skipped,
  9 min 44 s. An earlier run caught 2 `test_engine_retiring` failures from the
  first M29 version: the other-port check ran before the wait for an engine
  that is shutting down. It was moved after that wait, then re-verified live.
- `test_upgrade_rebind_fresh.py::test_fresh_rebind_writes_current_templates_not_stale_in_memory`
  passes on Mac, and it spawns a real interpreter.

## 3. §4 Real upgrade 0.3.168.1 → 0.3.169 (headline)

0.3.168.1 was built from `upstream/main` in a clean worktree with only the
version changed, then installed. This repo was enrolled with it (2 min 35 s,
9,079 chunks) before the drift was planted.

| Check | Result |
|---|---|
| `scubiee upgrade` exit / wall time | **0 / 11.0 s** (Windows: n/a) |
| `ok`, old → new | **True**, 0.3.168.1 → **0.3.169** |
| Phases | detect, plan, snapshot, quiesce, swap, migrate, embeddings, accel, home_layout, daemon, lean, rebind, health, commit |
| `rebind.ok` / `fresh_process` / error | **True / True / None** |
| health installed / daemon | **0.3.169 / 0.3.169** |
| planted `OUTDATED GATE BODY` in `scubiee.mdc` | **restored byte-identical** |
| planted `mcp.json` drift (`CTX_STALE_KEY`, missing `CTX_TRACE_PARALLEL`) | **repaired** |
| `AGENTS.md` | unchanged |
| Engine after upgrade | 0.3.169, `ready` |
| LaunchAgent `com.contextengine.supervisor` | running. `launchctl list` showed last exit `-9`: the upgrade stops the old supervisor and launchd restarts it (KeepAlive). Exactly one watchdog loop held the lock and the supervisor waited on it (M16 behaviour) |

**No-op upgrade on 0.3.169:** exit 0 in **2.7 s** (Windows 9 s). `scubiee.mdc`
and `AGENTS.md` mtimes unchanged. `mcp.json` changed **only** in
`/mcpServers/scubiee/env/CTX_SCUBIEE_BUILD`.

Cursor reconnect: Cursor's `scubiee-mcp-bridge` and `scubiee-mcp` restarted
cleanly after the reload (16:04:56). The live MCP checks are in §6.

## 4. §5 Ignore hardening on case-insensitive APFS

APFS (like NTFS) cannot hold `Build/` and `build/`, or `Vendor/` and
`vendor/`, in one folder. Each pair was placed under a different parent:
`Build/` at the root vs `web/build/`, and `p1/Vendor/` vs `p2/vendor/`. The
indexed file list was read from the store's `chunks.jsonl`, not inferred from
search.

| Created | Expected | Result |
|---|---|---|
| `Build/Build.cs` | indexed | **indexed** |
| `web/build/out.js` | ignored | **ignored** |
| `src/build/__init__.py` + `core.py` | indexed (package) | **indexed** (`core.py`; the empty `__init__` has no chunks) |
| `p1/Vendor/lib.go` | indexed | **indexed** |
| `p2/vendor/lib.go` | ignored | **ignored** |
| `myenv/pyvenv.cfg` + `myenv/lib/x.py` | ignored | **ignored** |
| `venv311/x.py`, `.venv-old/x.py` | ignored | **ignored** |
| `static/app.min.js` | ignored | **ignored** |
| `data/blob.json` (98 KB, one line) | ignored | **ignored** |
| `secret_build/` in root `.gitignore` | ignored | **ignored**, also after edit + `scubiee sync` |
| `normal.py` | indexed | **indexed** |

- **Sync:** deleting `web/build/out.js` and the indexed `Build/Build.cs`, and
  editing `normal.py`, all synced in one `scubiee sync` (2.8 s, ok). The new
  symbol was findable at once with high confidence, and `Build/Build.cs` left
  the index.
- **Startup prune:** plain `node_modules/x.js` is ignored from the start, so
  it never reaches the index and leaves nothing to prune. To exercise the prune
  path, `later/keep.py` was indexed first, then `later/` was added to the root
  `.gitignore` and the engine restarted. The log shows
  `[reconcile:start] enqueued 2 drift + 0 ghost prune + 1 ignored prune path(s)`
  and the chunk was removed.
- **No normal source file was dropped.**

## 5. §6 Live battery

### On PyPI 0.3.169 (after the §4 upgrade)

| Phase | ms | Phase | ms |
|---|---|---|---|
| clean_slate | 2,497 | map_second | **182** |
| host_start | 1,108 | status_first | 0.5 |
| auto_warm | 1,589 | pack_first | 26 |
| settle | 1,028 | expand_first | 128 |
| settle_join_embedder | 224 | idle_hold | 120,359 |
| map_first | **126** | post_idle_map | **210** |
| | | post_idle_pack | 24 |
| | | host_stop / unload | 1.6 / 120,863 |

- **Lane A:** 15/15 `ok=True`, no errors. `map_second` is 182 ms on Mac,
  comfortably under 1 s (Windows 542–1,182 ms).
- **`warm_contract`:** `failed: 0`. Warm-ready 615 ms,
  `first_map_after_ready` **99 ms**, `map_after_idle_ms` **111 ms**.
- **`ship_check`:** `ok`, errors `[]`, 371 ms. Preview shows `phase=dense`
  and `version=0.3.169`.

### On the final fix build (this branch, M28–M30 applied, ce8e097)

| Phase | ms | Phase | ms |
|---|---|---|---|
| clean_slate | 2,797 | map_second | **172** |
| host_start | 1,151 | status_first | 0.5 |
| auto_warm | 1,619 | pack_first | 26 |
| settle | 3,056 | expand_first | 105 |
| settle_join_embedder | 214 | idle_hold | 120,386 |
| map_first | **128** | post_idle_map | **191** |
| | | post_idle_pack | 24 |
| | | host_stop / unload | 4.6 / 121,085 |

- **Lane A:** 15/15 `ok=True`, no errors.
- **`warm_contract`:** `failed: 0`. Warm-ready 516 ms, first map 82 ms,
  after idle 111 ms.
- **`ship_check`:** `ok`, errors `[]`, 343 ms, `phase=dense`,
  `version=0.3.169`.
- **Fresh MCP worker, first `map find`:** 44 / 150 / 50 ms.
- An earlier fix-build run (before the M29 ordering fix in §7) also passed
  15/15. Its `unload` passed in 1 ms instead of waiting out the debounce.

## 6. §7 Targeted regressions (0.3.163–0.3.167)

The MCP checks drive `scubiee-mcp-bridge` over stdio with the exact command and
env from `.cursor/mcp.json` (MCP initialize, `notifications/initialized`,
`tools/call map`). This is the same path Cursor uses, with exact timings.

1. **Engine-down recovery (M27 + 0.3.163): PASS.**
   - Warm find 69 ms. Then `kill -9` on the engine and confirm `/health` is down.
   - The next MCP `map find` starts a new engine, returns the correct result
     with high confidence, `warm_phase` is `dense` immediately, and the
     following find takes 76–117 ms.
   - Recovery wall time over 4 runs each:

     | Build | Recovery times | Note |
     |---|---|---|
     | Stock 0.3.169 | 8.1, 9.6, 5.4, 8.5 s | |
     | Fix build | 8.9, 6.9, 7.0 s | 14.6 / 12.8 / 5.4 s right after the battery |

   - No difference between builds; the slower runs follow heavy activity.
2. **First find after worker (re)start (0.3.167): PASS.** Three fresh
   bridge+worker spawns: initialize 118–165 ms, **first `map find` 79–187 ms**
   (target < 1 s; Windows 344–386 ms). All returned the right symbol at high
   confidence.
3. **Custom port (0.3.165): PASS for a port switch. Bug when the default engine is still running (M29).**
   - Switch works: with the default engine stopped,
     `CTX_ENGINE_URL=http://127.0.0.1:8799 scubiee engine start` listens on
     8799, and `scubiee map` with the same env answers in 0.1 s.
   - Bug: with the default engine still on 8765, `engine start` returned
     `ok: true, already_running: true, url: …8799` while nothing listened on
     8799, and `map` printed "starting it… still warming – waiting…" for
     **93 s**, then exited 1 with Connection refused. Fixed (see M29).
4. **`doctor` mid-sync (0.3.165): PASS.** 400 generated files (12 functions
   each) added to this repo while `scubiee doctor` ran 12 times during the
   sync. All exited 0, none said "corrupt" or "rebuild index", and the run that
   hit the publish window reported `publication_updating`. After deleting the
   files and syncing: 0 probe chunks left, `doctor` rc 0.
5. **`wipe --all --keep-package` (0.3.166): PASS.** Exit 0 in 5.7 s, audit
   clean, `next: Re-run: scubiee setup && scubiee init .`. The tool dir and
   `scubiee --version` (0.3.169) survived. `~/.scubiee` and the LaunchAgent
   were removed and no Scubiee processes were left. Then:
   - `setup`: 2 min 42 s, re-downloads the model, MLX ~85 t/s.
   - `connect --cursor`: exit 0.
   - `init .`: 2 min 38 s, 9,087 chunks.
   - Cursor rules and MCP config managed again; supervisor running.

## 7. Bug register (continues from M27)

| ID | Sev | Area | Symptom | Root cause | Fix | Verified |
|---|---|---|---|---|---|---|
| M28 | med | sync / ignore prune | On macOS/Linux, `mark_dirty(prune=True)` queued an **outside** absolute path as a repo file (`/private/var/…/outside.py` → `private/var/…`). Windows unaffected (`C:/…` stays absolute) | `.strip("/")` ran before the `is_absolute()` check | 3baabd7: absolute paths are relativized to the repo or dropped; test extended with an inside-repo absolute path | targeted + full suite; was the only §3 failure |
| M29 | med | engine / CLI | With the default engine running, `CTX_ENGINE_URL=…:8799 scubiee engine start` reported ok/already_running for 8799 (nothing there), and `scubiee map` hung ~93 s, then failed | `is_running()` trusts the lock's live pid without comparing its recorded URL; `engine start` also forced `ok=True` whenever any engine pid was alive | 57e6c8b: `engine_running_elsewhere()` makes start/ensure refuse with `engine_on_other_url` (running URL + hint), checked **after** waiting for a retiring engine; `engine start` exits 1; `map` reports it at once | 6 new tests (fail on old code). Live: `engine start` exit 1 with reason; `map` exit 1 in **0.07 s** (was 93 s); default engine untouched; plain port switch still works |
| M30 | low | map UX | `scubiee map` in a repo that is not enrolled printed `RuntimeError: engine /v1/search failed: HTTPError: HTTP Error 409: Conflict` | `_http` discarded the engine's JSON body (`error: requires_initialize`) and retried 4xx | ce8e097: 4xx raises the engine's reason + hint, and `requires_initialize` says "`<root>` is not enrolled with Scubiee — run `scubiee init .`". No retry on 4xx; 5xx still retried | 2 new tests. Live: the new message after a wipe un-enrolled the scratch repo |
| M31 | med | upgrade | Minutes after 0.3.170 was published, `scubiee upgrade` planned 0.3.169 → 0.3.170 but reinstalled 0.3.169, and the report still said ok / "Upgrade complete" | the swap ran an unpinned `uv tool install --force scubiee`, which resolved from uv's cached PyPI index (still 0.3.169 ~10 min later); an unchanged version was only a warning | c7c71d0: install `scubiee==<target>` with `--refresh-package scubiee`; an unchanged version fails with `package_not_updated` + retry hint | 2 new tests (fail on old code). Live, with uv's cache still resolving 0.3.169: fix build 0.3.169.1 → **0.3.170** in 13.8 s, rebind fresh, health 0.3.170/0.3.170 |
| M32 | med | upgrade | Right after 0.3.171 was published, `scubiee upgrade` saw `latest 0.3.171, update_available: true` yet targeted the installed version, did nothing and reported ok | the CLI checked PyPI first (a stale CDN node still said 0.3.170, so `skip_package=True`), then `run_upgrade` checked again; `skip_package` overrode the second, newer answer. PyPI's project JSON is CDN-cached (`max-age=900`) | e11ee7b: the CLI passes its check into `run_upgrade`, so one answer decides both | new test; live in §10 |

### Observations (not bugs)

- **Repo looked un-enrolled at the start.** It had been un-enrolled after the
  previous session (registry empty, `AGENTS.md` emptied on Oct 19 17:21).
  That is why Cursor's Scubiee MCP was gone and `.cursor/rules/scubiee.mdc`
  held the "GATE 0, not managed" rule. The full suite's conftest guard wrote
  identical bytes back (mtime changed, content didn't). It was not a
  test-isolation leak.
- **Agent tool lists don't refresh in-session.** After a reload, Cursor's
  bridge was up at once, but an agent's tool list only refreshes on its next
  turn. The MCP checks above therefore use the stdio driver.

## 8. Go / no-go

| Gate | Result |
|---|---|
| §3 targeted tests | **pass** (after M28; 1 failure on stock main) |
| §4 real + no-op upgrade | **pass**, every flag as required |
| §5 ignore hardening on APFS | **pass**, every row, no false positives |
| §6 live battery | **pass** on 0.3.169 and on the fix build |
| §7 regressions | no high-severity finding (M29 medium, fixed) |

- **0.3.169 is production-ready on macOS.**
- M28–M30 shipped in 0.3.170. M31 (found while verifying the 0.3.170 release) shipped in 0.3.171, and M32 (found verifying 0.3.171) ships in 0.3.172. It lives in the *installed* version's upgrade code, so it takes effect from upgrades run on 0.3.171 onward. On 0.3.170 or older, if `scubiee upgrade` reports the old version, rerun it after a few minutes.
- **Full suite with all fixes:** 2,098 passed, 0 failed.

## 9. State left behind

- Installed: wheel built from this branch, reporting 0.3.169 (includes M28–M30).
  Reinstall `scubiee==0.3.169` from PyPI for the plain release build.
- `setup` done, this repo enrolled (9,087 chunks), Cursor connected, engine
  running on 8765.
- `/tmp/scu_ign` (scratch repo) is no longer enrolled after the keep-package
  wipe.
- Init-generated `AGENTS.md`, `.copilot/*` and `.kiro/*` changes are not
  committed.
