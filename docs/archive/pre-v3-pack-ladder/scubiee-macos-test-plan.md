# Scubiee — macOS Cross-Platform Reliability Test Plan

_Target: an agent running on macOS (Apple Silicon preferred; also note Intel if available)._
_Version under test: **0.3.133** (published to PyPI; includes the BUG-MH graph-lane fix and the QA-4 `/health` warm_phase fix)._
_Goal: confirm Scubiee is reliable on macOS the same way it was verified on Windows/DirectML. Reference the Windows results in `docs/scubiee-qa-findings.md` and the architecture in `docs/scubiee-overview.md`._

---

## 0. Read this first — what you're doing and why

Scubiee is a **local AI code-context engine + MCP server**. It indexes a repo and answers "where is the relevant code?" for an AI agent, via three surfaces: an **MCP server** (the `@scubiee/*` tools), a local **HTTP engine** on `127.0.0.1:8765`, and a **CLI** (`scubiee <cmd>`). It was QA'd thoroughly on Windows (DirectML GPU). Your job is to repeat that QA on **macOS** and confirm the platform-specific pieces work, because these differ from Windows:

- **Embedder backend:** macOS uses **MLX (Metal GPU)** or **CoreML** instead of Windows DirectML. This is the single biggest platform difference and the most likely place for bugs. (Windows-only file `_minhash.py` bug we fixed was platform-agnostic, but the embedder path is genuinely different here.)
- **Process/lifecycle management:** macOS uses a **launchd LaunchAgent** (plist at `~/Library/LaunchAgents/`), not a Windows service/watchdog process.
- **Paths:** config/state live under `~/Library/Application Support/…`, `~/.scubiee/`, and `~/Library/Logs/`.
- **CPU fallback:** if MLX/CoreML is unavailable, the embedder should fall back to FastEmbed/CPU — that path must be exercised too.

**How to record results:** create `docs/scubiee-macos-findings.md` and log every check with: what you ran, the observed output, and PASS / FAIL / OBSERVATION. Use the same severity legend as the Windows doc: **BUG** (broken), **ISSUE** (rough edge), **OBS** (by-design nuance), **OK** (verified). Cross-reference any Windows finding IDs (QA-1..QA-9, BUG-MH) if you see the same or different behavior on macOS.

**Ground rules:**
- Do **not** run destructive commands (`scubiee wipe`, `remove`, `halt`, force deletes) except in the dedicated teardown step, and only on throwaway test data.
- Clean up any test files you create (see §10). Never commit test artifacts.
- If the real `@scubiee/*` MCP tools are available to you, use them for the MCP section (that's what "test the MCP" means). Otherwise use the CLI `scubiee map|pack|expand|search`.
- Prefer writing command output to a file and reading it back if your shell interleaves stderr noise.

---

## 1. Environment capture (do this first)

Record the baseline so results are interpretable.

```bash
sw_vers                       # macOS version
uname -m                      # arm64 (Apple Silicon) or x86_64 (Intel)
sysctl -n machdep.cpu.brand_string
python3 --version
which scubiee || echo "scubiee not on PATH"
```

Capture:
- macOS version + chip (M1/M2/M3/M4 or Intel).
- Whether this is Apple Silicon (MLX/Metal expected) or Intel (CPU/CoreML path).
- Python version and how Scubiee is installed (uv tool vs in-repo).

**Expected:** Apple Silicon → MLX/Metal is the target accel. Intel → CPU/CoreML fallback.

---

## 2. Install the latest published version

Scubiee **0.3.133** has been **built and published to PyPI** (this is the build that contains both bug fixes). Install it directly — do **not** build from the working tree, since you want to test exactly what shipped.

```bash
# Install (or upgrade to) the published 0.3.133 release from PyPI as a uv tool:
uv tool install --force "scubiee==0.3.133"        # pin the version explicitly
# or just latest:  uv tool install --force scubiee
# (pipx works too:  pipx install --force scubiee==0.3.133)

# Confirm the installed binary and version:
which scubiee
scubiee --help | head -5
curl -s http://127.0.0.1:8765/health | grep -o '"version":[^,]*'   # after the engine starts
```

Then **restart Kiro** so it reconnects to the freshly installed MCP server, wait ~15–20s for the engine to warm, and begin the tests below.

Checks:
- **[ ] PASS/FAIL** Installed version is **0.3.133** (check `/health` `version` or `scubiee status` meta). If it isn't, stop and re-install — the rest of the plan assumes 0.3.133.
- **[ ] PASS/FAIL** `scubiee --help` lists ~40 subcommands (index, resources, test, preflight, doctor, certify, register, initialize, activate, pause, resume, sync-now, rebuild, remove, never-index, list, settings, search, status, gate, map, pack, expand, sync, serve, dashboard, engine, mcp, init, setup, wipe, stop, halt, unlock-tool, heal, migrate, diagnose, connect, disconnect, upgrade).
- **[ ] PASS/FAIL** After restarting Kiro, the `@scubiee/*` MCP tools are callable and `gate`/`status` report the repo as managed.
- **[ ] OBS** Note any macOS-specific install friction (Gatekeeper, quarantine, codesigning prompts, `xcrun`/CommandLineTools requirements).

> This build includes both Windows-fixed bugs (BUG-MH graph-lane `MinHash.update_batch`, and QA-4 `/health` warm_phase). §5 and §9.5 verify they don't reproduce on macOS.

---

## 3. Accelerator / embedder backend (the key macOS difference)

This is the most important macOS-specific area. On Apple Silicon the embedder should use **MLX on the Metal GPU**; verify it does, and that it produces correct results and falls back gracefully.

```bash
scubiee resources          # hardware snapshot + recommended accel profile
scubiee preflight          # dependency + capability report (faiss, mlx, etc.)
```

Checks:
- **[ ] PASS/FAIL** `scubiee resources` reports an Apple-appropriate `recommended_accel` profile (expect `mlx` on Apple Silicon; `cpu`/`coreml` otherwise).
- **[ ] PASS/FAIL** `scubiee preflight` shows the embedder capability is satisfied (MLX present on Apple Silicon, or a clean CPU fallback). `ok:true`.
- **[ ] PASS/FAIL** On first warm-up, the engine logs the backend. Look for stderr lines like `[embed] backend=mlx`, `[embed] device=gpu`, `[embed] metal=true`, `[embed] mlx_device=…`, or `[embed] MLX ready in …ms`. Confirm **Metal is actually used** (`metal=true`), not a silent CPU fallback.
- **[ ] PASS/FAIL** Force the fallback and confirm it works: set `CTX_EMBED_BACKEND=fastembed` (or `cpu`) and restart the engine; searches must still return sensible dense results (just slower). Then unset and confirm it returns to MLX.
- **[ ] BUG watch** If `CTX_EMBED_BACKEND=mlx` is set but the `mlx` package is missing, the code is designed to **refuse** and raise a `CapabilityError` (not silently fall back). Verify that refusal happens rather than a confusing crash.
- **[ ] OBS** Record embed dimensions (expect 768, CodeRankEmbed) and note the model/backend from `scubiee status` meta (`embed_model`, `embed_backend`).

**Why this matters:** dense retrieval quality and warm-up time both depend on this path. A macOS-specific embedder bug would silently degrade `map`/`pack`/`search` ranking. Compare a few `map` results here against the Windows findings for the same queries to confirm ranking is consistent.

---

## 4. Lifecycle & process management (launchd)

macOS uses a launchd LaunchAgent instead of the Windows watchdog. Verify the engine starts, stays alive, and stops cleanly.

```bash
scubiee engine status
scubiee engine start        # if not already running
scubiee engine status       # confirm running + healthy
```

Checks:
- **[ ] PASS/FAIL** `scubiee engine start` brings the engine up and `engine status` reports `running:true`, `health.ok:true`.
- **[ ] PASS/FAIL** A LaunchAgent plist exists at `~/Library/LaunchAgents/` (label starts with the Scubiee supervisor label). Confirm with `ls ~/Library/LaunchAgents/ | grep -i scubiee` and `launchctl list | grep -i scubiee`.
- **[ ] PASS/FAIL** Supervisor log is being written at `~/Library/Logs/scubiee-supervisor.log` (tail it during a start).
- **[ ] PASS/FAIL** After a manual `scubiee engine stop`, the engine goes down and (if the LaunchAgent is registered) is kickstarted back up as designed — confirm the intended auto-restart behavior, and that it does **not** thrash (repeated rapid restarts).
- **[ ] PASS/FAIL** Reboot test (optional but valuable): confirm whether the LaunchAgent auto-starts the engine after a logout/login or reboot, matching the documented autostart behavior.
- **[ ] OBS** Note the `~/.scubiee/` directory contents (watchdog.log, warm phase file, prefs.json, id/registry). Compare to the Windows `%USERPROFILE%\.scubiee\` layout.

---

## 5. Warm-up timing

Measure cold → soft-ready → dense-ready on macOS and compare to Windows (~4s soft / ~11s dense on the Windows/DirectML box).

```bash
scubiee engine stop
# then start and poll:
scubiee engine start
# poll health repeatedly and time the transitions:
for i in $(seq 1 40); do
  curl -s http://127.0.0.1:8765/health | python3 -c 'import sys,json,time; d=json.load(sys.stdin); print(int(time.time()), d.get("warm_state"), "soft="+str(d.get("soft_search_ready")), "embed="+str(d.get("embedder_loaded")), "phase="+str(d.get("warm_phase")))'
  sleep 1
done
```

Checks:
- **[ ] Record** time to `soft_search_ready:true` (BM25/index usable, `map` works).
- **[ ] Record** time to `embedder_loaded:true` / `dense_ready:true` (full dense ranking).
- **[ ] PASS/FAIL (QA-4 regression):** while warm, `/health` must report a **live** `warm_phase` (`soft`/`dense`), **not** a stuck `"down"`. This was a Windows bug we fixed in `ce_service.py` — confirm the fix holds on macOS. Cross-check that `warm_state`, `embedder_loaded`, `dense_ready`, and `warm_phase` all agree.
- **[ ] OBS** Note whether MLX/Metal warm-up is faster/slower than DirectML. Report honest numbers; don't assume parity.

---

## 6. MCP tools (all 8)

Use the real `@scubiee/*` MCP tools if available; otherwise the CLI equivalents (`scubiee map|pack|expand|search|status|gate`). Test each with a valid input and at least one error/edge input. Mirror the Windows §1 tests.

For each, record PASS/FAIL + notable output:
- **[ ] `gate`** — returns `1:<project_id>` managed line.
- **[ ] `status`** — `summary`, `full`, and `gate` detail levels all work; `full` shows engine meta, keeper, dirty ledger, lifecycle.
- **[ ] `map`** — enriched query returns ranked cards + `suggested_seeds`, `dense:true`. A vague one-word query sets `weak_match:true`. **Compare top results to the Windows run for the same query** to confirm ranking parity across the MLX vs DirectML embedder. _(Windows QA-2: `suggested_seed` sometimes returns a `_`-private helper against the tool's own guidance — check if macOS does the same.)_
- **[ ] `pack_context`** — valid `seed_file`+`seed_symbol` returns a coherent heatmap with `loc` spans; `include_bodies=1` + `budget_chars` returns bodies within budget; bad seed → clean `ok:false` error with hint; missing `seed_file` → `"seed_file required"`.
- **[ ] `expand_context`** — `direction=callees`/`callers`/`effects` all return sensible deltas; `already_in_pack` dedup flag appears; empty case gives `empty_reason`. _(Windows QA-3 OBS: `callers` is structural-only, not every textual ref — expected.)_
- **[ ] `collect_hot_context`** — explicit `ids=` returns bodies within `max_chars`.
- **[ ] `workspace`** — `show` returns the session brain (topic/heatmap/pins); `pin` adds a file; `clear` resets everything.
- **[ ] `expand`** — a valid `file::symbol` handle returns the body; a bad handle → clean `ok:false` with hint.

---

## 7. HTTP API

Exercise the local engine directly. Mirror the Windows §2 tests.

```bash
# GET endpoints:
for p in /health / /status /v1/status /api/settings /v1/settings /v1/resources /dashboard; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8765$p"); echo "$p -> $code"
done
curl -s -o /dev/null -w "unknown -> %{http_code}\n" http://127.0.0.1:8765/v1/nope_zzz   # expect 404

# POST retrieval (adjust repo path):
REPO="$HOME/path/to/context-engine"
curl -s -X POST http://127.0.0.1:8765/v1/search   -H 'content-type: application/json' -d "{\"query\":\"create_mcp tool registration\",\"repo\":\"$REPO\",\"k\":3}" | head -c 400; echo
curl -s -X POST http://127.0.0.1:8765/v1/grep     -H 'content-type: application/json' -d "{\"pattern\":\"def create_mcp\",\"repo\":\"$REPO\",\"k\":5}" | head -c 200; echo
curl -s -X POST http://127.0.0.1:8765/v1/outline  -H 'content-type: application/json' -d "{\"path\":\"packages/pipeline/mcp_locate.py\",\"repo\":\"$REPO\"}" | head -c 200; echo
curl -s -X POST http://127.0.0.1:8765/v1/read_span -H 'content-type: application/json' -d "{\"path\":\"packages/pipeline/mcp_locate.py\",\"start\":1549,\"end\":1559,\"repo\":\"$REPO\"}" | head -c 200; echo
curl -s -X POST http://127.0.0.1:8765/v1/follow_imports -H 'content-type: application/json' -d "{\"path\":\"packages/pipeline/mcp_locate.py\",\"repo\":\"$REPO\"}" | head -c 200; echo
curl -s -X POST http://127.0.0.1:8765/v1/grep_ident -H 'content-type: application/json' -d "{\"ident\":\"create_mcp\",\"repo\":\"$REPO\",\"k\":5}" | head -c 200; echo
curl -s -X POST http://127.0.0.1:8765/v1/graph_neighbors -H 'content-type: application/json' -d "{\"paths\":[\"packages/pipeline/mcp_locate.py\"],\"query\":\"create_mcp\",\"repo\":\"$REPO\"}" | head -c 200; echo
curl -s -X POST http://127.0.0.1:8765/v1/query_graph -H 'content-type: application/json' -d "{\"question\":\"how are MCP tools registered\",\"repo\":\"$REPO\",\"keep\":6}" | head -c 200; echo
```

Checks:
- **[ ] PASS/FAIL** All GET endpoints return 200; unknown returns 404.
- **[ ] PASS/FAIL** `/health` reports the correct live `warm_phase` (QA-4 regression — see §5).
- **[ ] PASS/FAIL** All POST retrieval endpoints return `ok:true` with the correct body shapes.
- **[ ] ISSUE watch (QA-5):** `graph_neighbors` needs `paths[]`, `query_graph` needs `question`; a wrong shape returns a **bare 400 with no JSON error envelope** on Windows. Confirm the same on macOS and note it.
- **Do NOT** call `/v1/shutdown`, `/shutdown`, `/reload`, or `/v1/session/end` except in teardown — they disrupt the engine.

---

## 8. CLI surface

Mirror the Windows §4 tests. Run the safe read commands; skip destructive ones until teardown.

```bash
scubiee status
scubiee gate
scubiee list
scubiee settings
scubiee search "create_mcp tool registration"
scubiee map "MCP tool registration create_mcp _tool gate status"
scubiee pack "create_mcp registration _tool gate status map" --seed-file packages/pipeline/mcp_locate.py --seed-symbol create_mcp
scubiee expand --node "packages/pipeline/mcp_locate.py::create_mcp" --direction callees
scubiee engine status
scubiee preflight
scubiee doctor
scubiee resources
scubiee certify
```

Checks:
- **[ ] PASS/FAIL** Each command returns valid JSON / expected output and exit code 0.
- **[ ] OBS (QA-6)** `pack` takes `query` as a required **positional** (plus `--seed-file`/`--seed-symbol`); `expand` requires `--node`. Confirm the arg shapes match Windows.
- **[ ] OBS (QA-7)** `doctor` may flag stale registry entries (dead test enrollments). Note any it reports on macOS.
- **[ ] PASS/FAIL** `certify` runs its release-certification gate with `failures:[]`.
- **[ ] OBS** Note any macOS shell/stderr noise that interferes with output capture (on Windows a Miniconda/pydantic warning swallowed stdout — check for a macOS analog).

---

## 9. Lifecycle & sync propagation

Mirror the Windows §5 tests. Use a **unique marker symbol** so you can search precisely, and check the `hits[].file` field (not a raw text match — the search response echoes the query, which causes false positives; this bit us on Windows).

1. **New file:** create `packages/pipeline/zz_mac_synctest.py` with a unique function, e.g. `zzmac_marker_alpha()`. POST `/v1/dirty` for the path, then poll `/v1/search` for the marker.
   - **[ ] Record** hot-lane latency (Windows: ~360ms). Confirm `pack_context` can resolve the new symbol as a seed (graph lane).
2. **Delete:** delete the file, `/v1/dirty` it, and confirm it drops from `hits[].file` (check the field, not raw body).
   - **[ ] PASS/FAIL** File no longer in hits after settle.
3. **Rename:** create `zz_mac_rename_src.py`, index it, rename to `zz_mac_rename_dst.py`, `/v1/dirty` both.
   - **[ ] OBS (QA-9)** New path indexes immediately; old path may linger one reconcile pass before eviction. Confirm the old path eventually drops.
4. **Ignore rules:** create a file under an ignored dir (`sandbox/`, `testdata/`, `research/`, etc. — see `.scubieeignore`) with a unique symbol.
   - **[ ] PASS/FAIL** File exists on disk but is **not** indexed (`ignored_in_hits=0`).
5. **Graph lane health (BUG-MH regression):** touch a source file and force a sync/rebuild (`scubiee sync-now` or `scubiee rebuild`), then check the keeper `last_sync.warnings` in `/v1/search` output.
   - **[ ] PASS/FAIL** No `graph rebuild failed: 'MinHash' object has no attribute 'update_batch'` (or any `graph_error`). This was the high-severity Windows bug BUG-MH; confirm the fix holds on macOS. Then confirm `expand_context` on a symbol returns its real callees (graph edges intact).

---

## 10. Teardown & cleanup

- **[ ] ** Delete every `zz_mac_*` test file you created and `/v1/dirty` the paths to drop them from the index.
- **[ ] ** Remove any empty test dirs you created (e.g. a `sandbox/` you made just for the ignore test).
- **[ ] ** Confirm `find . -name "zz_mac_*"` returns nothing.
- **[ ] ** `git status` — confirm you left no stray test files staged/committed. Do **not** commit test artifacts.
- **[ ] ** Leave the engine in a healthy warm state (or stopped cleanly), your choice — note which.

---

## 11. What to deliver

Write `docs/scubiee-macos-findings.md` containing:
1. **Environment** (macOS version, chip, Apple Silicon vs Intel, backend used).
2. **Per-section results** (§2–§9) with PASS/FAIL/OBS and the actual output snippets.
3. **A consolidated issue register table** (same format as `scubiee-qa-findings.md` §6): ID, severity, area, summary, status.
4. **Cross-platform comparison:** for each Windows finding (BUG-MH, QA-1..QA-9), state whether macOS behaves the same, better, or worse. Explicitly confirm the two fixed bugs (BUG-MH graph lane, QA-4 `/health` warm_phase) do **not** reproduce on macOS.
5. **macOS-only findings:** anything platform-specific — MLX/Metal/CoreML behavior, launchd lifecycle, path/permission issues, Gatekeeper/codesign friction.
6. **Honest verdict:** is Scubiee reliable on macOS? What's proven, what's not (e.g. Intel path if you only tested Apple Silicon, large-repo scale, reboot autostart).

### Priorities if you're short on time
1. **§3 embedder backend (MLX/Metal)** — the biggest platform risk.
2. **§9.5 graph-lane/BUG-MH regression** and **§5/QA-4 warm_phase** — confirm the two fixes hold.
3. **§4 launchd lifecycle** — macOS-specific process management.
4. Everything else (MCP/HTTP/CLI parity) — should mostly match Windows, but verify.

---

## Appendix — key facts for the macOS agent

- **Engine:** local HTTP server on `127.0.0.1:8765`. GET `/health /status /v1/status /api/settings /v1/settings /v1/resources /dashboard`; POST `/v1/search /grep /outline /read_span /follow_imports /grep_ident /graph_neighbors /query_graph /dirty /note_locate /session_anchors /reopen_anchors` (+ control: `/v1/shutdown /reload /v1/session/end` — avoid).
- **8 MCP tools:** `gate`, `status`, `map`, `pack_context`, `expand_context`, `collect_hot_context`, `workspace`, `expand`.
- **Retrieval:** graph + BM25 + dense (CodeRankEmbed 768-dim) fused; FAISS + int8 quant. macOS dense backend = MLX (Metal) or CoreML; Windows = DirectML.
- **Two sync lanes:** hot BM25 (sub-second) + deferred graph catch-up (~30s or after clients disconnect). `pack`/`expand` depend on the graph lane; `search`/`map` ride the hot lane.
- **Ignore rules:** `packages/pipeline/ignore.py` built-ins + repo `.scubieeignore` (sandbox/, testdata/, research/, experiments/, references/, design_benchmarks/, fixtures/).
- **macOS paths:** LaunchAgent `~/Library/LaunchAgents/<label>.plist`; supervisor log `~/Library/Logs/scubiee-supervisor.log`; state `~/.scubiee/`; editor MCP config under `~/Library/Application Support/…`.
- **Env vars:** `CTX_EMBED_BACKEND` (`mlx`/`fastembed`/`cpu`/`coreml`), `CTX_EMBED_DEVICE`, `CTX_ENGINE_URL`, `CTX_GRAPH_CATCHUP_DELAY_S`, `CTX_KEEPER_DEFER_WHILE_CLIENTS`. In-repo runs need `PYTHONPATH=packages`; installed-tool runs must not set it.
- **Reference docs:** `docs/scubiee-overview.md` (architecture), `docs/scubiee-qa-findings.md` (the Windows QA pass this plan mirrors).
