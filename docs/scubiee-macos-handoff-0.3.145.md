# Scubiee macOS Handoff — v0.3.145 reliability + perf verification

**You are:** an autonomous coding agent running on a **macOS** machine (Apple
Silicon preferred; note Intel if that's what you have), with the Scubiee
`@scubiee/*` MCP tools connected and a terminal.

**Your job:** repeat — on macOS — the production-hardening verification that was
done on Windows/DirectML for **v0.3.145**, find any macOS-specific bugs, **fix
them**, and write a findings/handoff doc. macOS is the one tier that has NOT been
tested with the new work. You are the gate before macOS can be called launch-ready.

**Authority:** you have a yes to do whatever is needed — install, run tests,
edit code, rebuild, commit on a branch. Do **not** push or open PRs without being
asked. Do **not** run destructive commands (`scubiee wipe`, `remove`, `halt`,
force deletes) except in the dedicated teardown step on throwaway data.

**Deliverable:** `docs/scubiee-macos-findings-0.3.145.md` (template in §12). Log
every check with the exact command, observed output, and PASS / FAIL / OBS, plus
a bug register and an honest verdict.

---

## 0. Context — what changed in 0.3.145 and why macOS matters

Scubiee is a local AI code-context engine + MCP server. It indexes a repo and
answers "where is the relevant code?" through three surfaces:
- **MCP server** — the shipped tools are **`map`** (with `config=find|focus`),
  **`gate`**, and **`status`**. (Older docs mention `pack_context`,
  `expand_context`, `collect_hot_context`, `workspace`, `expand` — those are
  **RETIRED**. If you see them referenced, the doc is stale.)
- **HTTP engine** on `127.0.0.1:8765`.
- **CLI** — `scubiee <cmd>`.

The Windows pass for 0.3.145 landed these changes. **Each is a macOS risk because
the embedder/accel and process-lifecycle layers are genuinely different on Mac:**

1. **Cold-start perf fix** — dense-ready used to trail soft-ready by ~15s because
   the embedder prewarm was scheduled *after* a ~26s AST-bundle revalidation that
   starved it. Fix: kick the dense prewarm immediately after warm-ready, and gate
   the AST revalidation on `embedder_loaded` so it can't starve the embedder
   during the cold window. **On Mac the embedder is MLX/Metal, not DirectML — the
   warm sequence timing is unverified here.**
2. **`/health` under embed load** — background health refresher keeps `/health`
   off the request-path disk I/O so it never stalls while embedding.
3. **Graph catch-up batching** — a catch-up rewrites the whole `graph.json` per
   merge (fixed ~2-4s cost). Bulk churn was sliced into N merges; now a
   catch-up-only drain merges all pending files in ONE rebuild. **Pure Python +
   NetworkX; should be platform-agnostic, but verify the timing on Mac.**
4. **ORT wheel-conflict (Windows-only root cause, but Mac has an analog)** — on
   Windows, fastembed's unbounded `onnxruntime` dep clobbered
   `onnxruntime-directml` and silently killed the GPU. **On macOS the dep is
   plain `onnxruntime` (<1.25) + `mlx`, so the Windows `onnxruntime-directml`
   clash does NOT apply — but see §5 for the Mac analog you must check.**
5. **In-engine ORT self-heal is detect-only** — the engine never runs pip against
   its own live site-packages (that corrupted installs on Windows). It only
   detects a broken accelerator and logs "run `scubiee setup --repair`".
6. **Connect-once / init-auto-applies hardening (new in 0.3.145 — platform-
   agnostic, so verify on Mac)** — `scubiee connect <tool>` records the tool in
   `~/.scubiee/connected_tools.json` once per machine; every subsequent `init`
   auto-restores and re-applies all saved tools to the repo. This path was made
   crash-safe (atomic write + `.bak` self-heal so a torn primary never silently
   resets to `[]`) and resilient (per-tool isolation on apply, so one failing
   tool can't block the others). **Pure Python + filesystem; should behave
   identically on Mac — confirm the state file, backup, and self-heal all work on
   the macOS home path, and that connect→init→reconnect round-trips cleanly.**

Reference docs: `docs/scubiee-performance-timings.md` (the Windows numbers you're
comparing against), `docs/scubiee-overview.md` (architecture),
`docs/scubiee-install-windows-dml.md` (the Windows ORT fix — read it to
understand the class of bug, then check the Mac analog).

---

## 1. Environment capture (do first)

```bash
sw_vers                                 # macOS version
uname -m                                # arm64 (Apple Silicon) or x86_64 (Intel)
sysctl -n machdep.cpu.brand_string
python3 --version
uv --version
which scubiee || echo "scubiee not on PATH"
```

Record: macOS version, chip (M1/M2/M3/M4 or Intel), Apple Silicon vs Intel,
Python + uv versions, how Scubiee is installed. On Apple Silicon the target accel
is **MLX (Metal)**; on Intel it's **CPU** (CoreML/FastEmbed).

---

## 2. Install v0.3.145

You have two options. **Prefer building from this checkout** so you test exactly
the code with the new fixes (0.3.145 may not be on PyPI yet).

### Option A — build + install from the checkout (recommended)
```bash
cd /path/to/context-engine
# Build the wheel (use the repo's python with deps; adjust if you use a venv):
PYTHONPATH=packages python3 -m build --wheel --outdir dist_prod
# Stop any running engine, then install the wheel as a uv tool:
scubiee engine stop 2>/dev/null || true
uv tool install --force --reinstall dist_prod/scubiee-0.3.145-py3-none-any.whl
```

> **Do NOT use the Windows override file** `packaging/uv-overrides-win-dml.txt` on
> macOS — it excludes `onnxruntime`, which macOS actually needs. The Windows
> conflict (`onnxruntime-directml`) does not exist on Mac.

### Option B — from PyPI if 0.3.145 is published
```bash
uv tool install --force "scubiee==0.3.145"
```

Then verify:
```bash
scubiee --version
scubiee engine start
sleep 20
curl -s http://127.0.0.1:8765/health | python3 -m json.tool | grep -E 'version|warm_state|dense_ready'
```

Checks:
- **[ ] PASS/FAIL** installed version is **0.3.145** (`/health` `version`).
- **[ ] PASS/FAIL** after restarting your IDE, the `@scubiee/*` MCP tools are
  callable; `gate` returns `1:<project_id>`; `status` reports warm + dense.
- **[ ] OBS** any macOS install friction (Gatekeeper, quarantine, codesign,
  `xcrun`/CommandLineTools, Metal/MLX wheel availability for your Python).

---

## 3. Accelerator / embedder backend (the #1 macOS risk)

```bash
scubiee resources     # hardware snapshot + recommended accel
scubiee preflight      # capability report (faiss, mlx, onnxruntime)
scubiee doctor         # deeper capability + provider check
scubiee certify        # release-certification gate (expect failures: [])
```

Checks:
- **[ ] PASS/FAIL** `resources` recommends `mlx` on Apple Silicon (`cpu`/`coreml`
  on Intel).
- **[ ] PASS/FAIL** `preflight`/`doctor` show the embedder capability satisfied —
  **mlx present and actually used on Apple Silicon**, not a silent CPU fallback.
- **[ ] PASS/FAIL** `certify` returns `ok:true` with `failures: []`. On Windows
  the Mac-only checks (`darwin_mlx`) are skipped; on Mac they must PASS. If
  `certify` fails on an mlx/coreml check, that's a **BUG** — investigate and fix.
- **[ ] PASS/FAIL** First warm logs the backend. Look in `~/.scubiee/engine.log`
  (or the supervisor log) for `[embed] ... device=mlx` / `backend=mlx` /
  `metal=true` / `MLX ready in …ms`. Confirm Metal is really used.
- **[ ] PASS/FAIL (capability refusal)** set `CTX_EMBED_BACKEND=mlx` with mlx
  absent (e.g. temporarily in a CPU-only venv) → the code must raise a clean
  `CapabilityError` ("requires FastEmbed + ONNX Runtime … Refusing silent …
  fallback"), NOT crash cryptically or silently use CPU. (See
  `packages/pipeline/embedder.py::_choose_backend`.)
- **[ ] PASS/FAIL (CPU fallback works)** set `CTX_EMBED_BACKEND=fastembed`,
  restart engine → dense search still returns sensible results (slower). Unset,
  restart → back to MLX.
- **[ ] OBS** record embed model (`nomic-ai/CodeRankEmbed`, dim 768) and
  throughput (t/s) from the log; compare to Windows DML (~35 t/s).

**Why:** every `map`/`focus` ranking depends on this. A Mac embedder bug silently
degrades retrieval. Run 2-3 of the same `map find` queries you'd run on Windows
and sanity-check that results are relevant (not scrambled).

---

## 4. Cold-start + warm sequence timing (new 0.3.144 fix — verify on Mac, still relevant in 0.3.145)

The Windows fix made dense-ready trail soft-ready by only ~2-9s instead of ~15s.
Verify the same ordering holds with the MLX warm path.

```bash
scubiee engine stop
# Record a start time, launch, and poll health milestones:
T0=$(python3 -c 'import time;print(time.time())')
scubiee engine start
for i in $(seq 1 60); do
  curl -s http://127.0.0.1:8765/health | python3 -c '
import sys,json,time
d=json.load(sys.stdin)
print(round(time.time(),1), "warm="+str(d.get("warm_state")),
      "soft="+str(d.get("soft_search_ready")),
      "dense="+str(d.get("dense_ready")),
      "phase="+str(d.get("warm_phase")))' 2>/dev/null
  sleep 1
done
```

Checks:
- **[ ] Record** seconds to `soft_search_ready:true` and to `dense_ready:true`.
- **[ ] PASS/FAIL** dense-ready should follow soft-ready by a small gap (seconds),
  **not** be stuck ~15s+ behind. If dense trails badly, check the engine log for
  an `ast bundle revalidated ms=…` line blocking the embedder — that's the exact
  Windows bug; the gate (`CTX_AST_REVALIDATE_GATE_ON_EMBED`, default on) should
  prevent it. If it reproduces on Mac, that's a **BUG** to fix.
- **[ ] PASS/FAIL** `/health` reports a live `warm_phase` (`soft`/`dense`), never
  a stuck `"down"` while warm.
- **[ ] OBS** compare MLX warm numbers to Windows DML cold-start (soft ~4-9s,
  dense ~14s). Report honest numbers; MLX may differ.

---

## 5. macOS ORT/accel install-robustness (the Mac analog of the Windows fix)

The Windows bug was `onnxruntime-directml` getting clobbered by generic
`onnxruntime`. **That specific clash does not exist on Mac** (Mac uses plain
`onnxruntime` + `mlx`). But verify the Mac analog:

```bash
# What ORT is installed, and does mlx import?
python3 - <<'PY'
import importlib.metadata as m
for p in ("onnxruntime","onnxruntime-directml","onnxruntime-gpu","mlx","fastembed"):
    try: print(p, m.version(p))
    except Exception as e: print(p, "ABSENT")
import onnxruntime as ort; print("ORT providers:", ort.get_available_providers())
PY
```

Checks:
- **[ ] PASS/FAIL** exactly ONE onnxruntime variant is installed — plain
  `onnxruntime` (NOT `-directml`/`-gpu`). If `onnxruntime-directml` somehow got
  installed on Mac, that's a **BUG** (wrong wheel for platform).
- **[ ] PASS/FAIL** `onnxruntime` version satisfies the pin `>=1.17,<1.25`. If
  fastembed's unbounded dep pulled `>=1.25`, note it — the Mac analog of the
  Windows unbounded-dep problem. If so, the fix is a Mac constraints/override file
  mirroring the Windows one (constrain `onnxruntime<1.25`), documented the same way.
- **[ ] PASS/FAIL (reinstall robustness)** run `uv tool install --force
  --reinstall` of the wheel again, then re-check providers + mlx import + a dense
  `map`. On Windows a plain reinstall silently broke the GPU. Confirm macOS
  survives a reinstall with MLX intact. If a reinstall breaks MLX/ORT, that's a
  **BUG** — design a Mac constraints file (same technique as
  `packaging/uv-overrides-win-dml.txt` but constraining onnxruntime version) and
  verify it fixes the reinstall.
- **[ ] PASS/FAIL (detect-only self-heal)** if the accelerator is broken, the
  engine log should print a detect-only WARNING pointing at `scubiee setup
  --repair` and must **not** try to pip-reconcile from inside the engine. Grep the
  log for the warning; confirm no in-engine pip mutation.
- **[ ] PASS/FAIL** `scubiee setup --repair` cleanly restores the accelerator with
  no engine running.

---

## 6. /health under embed load (new 0.3.144 fix, still shipped in 0.3.145)

Confirm the background health refresher keeps `/health` responsive while the
engine embeds a backlog.

```bash
# In one terminal, create churn to force embedding (see §9), then in another:
for i in $(seq 1 100); do
  /usr/bin/time -p curl -s -o /dev/null http://127.0.0.1:8765/health 2>&1 | grep real
  sleep 0.1
done
```

Checks:
- **[ ] PASS/FAIL** no `/health` request times out or blocks multiple seconds,
  even while the engine is embedding. Record p50/max.
- **[ ] OBS** compare to Windows (p50 ~2ms, no timeouts under load).

---

## 7. MCP tools + CLI surface (shipped `map`/`gate`/`status`)

Use the real `@scubiee/*` MCP tools if available; else the CLI
(`scubiee map|gate|status`). Note the surface is `find|focus` only.

- **[ ] `gate`** → `1:<project_id>`.
- **[ ] `status`** → ok, warm, dense, chunks, version.
- **[ ] `map config=find`** — an enriched code-vocab query returns ranked results
  with `suggested_seeds`, high/medium confidence. A vague one-word query returns
  low confidence. **Run the same queries you'd run on Windows and compare ranking**
  (MLX vs DML embedder parity).
- **[ ] `map config=focus names=[...]`** — a known symbol returns its body +
  callers/callees + siblings.
- **[ ] graceful degradation** — `map config=related`/`graph` should emit the
  "folds into find/focus" note and still return results (not error).
- **[ ] error handling** — nonsense query → low confidence + rewrite hint (no
  hallucinated confident match); missing focus symbol → clean "could not resolve".

Also run the CLI diagnostics and confirm exit 0 + valid output:
```bash
scubiee status; scubiee gate; scubiee list; scubiee settings
scubiee map "freshness choose_strategy incremental vs full sync decision" --config find
scubiee map --config focus --names choose_strategy
scubiee preflight; scubiee doctor; scubiee resources; scubiee certify
```

---

## 8. HTTP API

```bash
for p in /health / /status /v1/status /v1/resources /dashboard; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8765$p"); echo "$p -> $code"
done
curl -s -o /dev/null -w "unknown -> %{http_code}\n" http://127.0.0.1:8765/v1/nope_zzz   # expect 404
```
- **[ ] PASS/FAIL** GET endpoints 200; unknown 404; `/health` live `warm_phase`.
- **Do NOT** call `/v1/shutdown`, `/reload`, `/v1/session/end` except in teardown.

---

## 9. Sync lanes — all types (hot-save, incremental, delete, rename, bulk/offline)

Use a **unique marker symbol** per file and check the returned **file path**, not
raw body text (the search echoes the query → false positives; this bit the
Windows run). Put test files under `scripts/perf/_mac_scratch/` so cleanup is easy.

1. **Hot-save** (modify a tracked file): append `def zzmac_hot_<rand>():` to an
   existing file; time until `map find` returns it. _(Windows ~2.5s.)_
2. **Incremental** (new file): create `_mac_new_<rand>.py` with a unique fn; time
   to searchable. _(Windows ~3s.)_
3. **Delete**: delete an indexed test file; time until it drops from results.
   _(Windows ~1.5s — deletes carry no embed.)_
4. **Live rename**: create+index `_mac_ren_old.py`, rename to `_mac_ren_new.py`;
   confirm new path searchable and old path drops. _(Windows: new ~2.2s, old ~4.2s.)_
5. **Bulk/offline + graph-catchup batching (new 0.3.144 fix, still shipped in 0.3.145)**: `scubiee engine
   stop`, create ~80 small files under the scratch dir, `scubiee engine start`,
   then watch `~/.scubiee/engine.log` for the reconcile + graph catch-up.
   - **[ ] PASS/FAIL** the offline reconcile enqueues the batch (`[reconcile:start]
     enqueued N drift …`) and drains; all files become searchable.
   - **[ ] PASS/FAIL (batching)** the ~80 catch-up files should merge in **one**
     (or very few) `graph catch-up` passes, **not** N separate ~4s rebuilds. Grep
     the log: `grep "graph catch-up" ~/.scubiee/engine.log`. Count the merges —
     one big batch is the fix working. Record the per-merge `merge_ms`/`ms`.
   - **[ ] PASS/FAIL** `index_fresh` is False during the drain and flips True when
     caught up; search stays usable throughout.
   - **[ ] OBS** compare total drain time + per-merge graph cost to Windows
     (per-merge ~4s; 80 files = one batch).

---

## 10. launchd lifecycle (macOS-specific)

```bash
scubiee engine status
ls ~/Library/LaunchAgents/ | grep -i scubiee
launchctl list | grep -i scubiee
ls -la ~/Library/Logs/ | grep -i scubiee
```
- **[ ] PASS/FAIL** engine starts/stops cleanly; LaunchAgent plist exists;
  supervisor log is written.
- **[ ] PASS/FAIL** after `scubiee engine stop`, auto-restart behaves as designed
  and does NOT thrash (rapid repeated restarts).
- **[ ] PASS/FAIL (idle)** with no client connected, the engine idles to standby
  per policy (Windows: ~2 min after disconnect). Confirm the Mac timing.
- **[ ] OBS** `~/.scubiee/` contents vs Windows `%USERPROFILE%\.scubiee\`.

---

## 11. If you find a bug — fix it

You have authority to fix. For each bug:
1. **Reproduce** it in isolation and capture the exact failing command/output.
2. **Root-cause** it — read the relevant code (use `map`/`focus` to locate).
   Likely macOS-specific areas: `packages/pipeline/mlx_mac.py`,
   `coreml_mac.py`, `accel.py`, `embedder.py`, launchd lifecycle in
   `lifecycle_runtime.py`.
3. **Fix** at the root, not a band-aid. Match existing patterns. Gate risky
   behavior behind an env knob with a safe default (as the Windows fixes did).
4. **Add/adjust a test** if there's a reasonable unit for it.
5. **Verify**: run the touched-suite tests, rebuild the wheel, reinstall, and
   re-run the failing scenario end-to-end on the live engine.
6. **Record** the bug + fix in the findings doc (ID, severity, root cause, fix,
   verification). Commit on a branch with a clear message. Do not push.

Run the offline test suite to catch regressions (expect fastembed/mlx-dependent
failures only if your test python lacks those — note which are env-only vs real):
```bash
PYTHONPATH=packages python3 -m pytest tests/ -q
# Mac-relevant suites to watch: test_mlx_backend, test_accel_cpu_fallback,
# test_coderank_fp16, test_embedder_progress, test_cpu_only_laptop_path.
```

---

## 12. Deliverable — `docs/scubiee-macos-findings-0.3.145.md`

Include:
1. **Environment**: macOS version, chip, Apple Silicon vs Intel, backend used,
   install method, scubiee version.
2. **Per-section results** (§2–§10): PASS/FAIL/OBS with the actual output
   snippets. Lead with §3 (embedder/MLX), §4 (cold-start), §5 (install
   robustness), §9.5 (graph-catchup batching) — the highest-risk new areas.
3. **Bug register** (table): ID, severity (BUG/ISSUE/OBS/OK), area, summary,
   root cause, fix (commit SHA if fixed), status.
4. **Cross-platform comparison**: for each fix (cold-start, health-under-
   load, graph-catchup batching, ORT/accel robustness, detect-only self-heal),
   state whether macOS behaves the same / better / worse, with numbers.
5. **macOS-only findings**: MLX/Metal/CoreML behavior, launchd lifecycle,
   path/permission/Gatekeeper issues, any Mac ORT constraint needed.
6. **Honest verdict**: is Scubiee reliable on macOS for launch? What's proven,
   what's not (Intel path if you only tested Apple Silicon, reboot autostart,
   large-repo scale).

### Priorities if short on time
1. **§3 embedder/MLX** — biggest platform risk.
2. **§4 cold-start ordering** + **§9.5 graph-catchup batching** — confirm the new
   perf fixes hold on Mac.
3. **§5 install/reinstall robustness** — does a Mac reinstall keep MLX? If not,
   build the Mac constraints file.
4. **§10 launchd lifecycle** — macOS-specific.
5. MCP/HTTP/CLI parity (§7/§8) — should match Windows; verify.

---

## 13. Teardown

```bash
rm -rf scripts/perf/_mac_scratch
# dirty the removed paths so the index prunes them, or let the keeper reconcile:
scubiee sync-now 2>/dev/null || true
find . -name "_mac_*" -o -name "zzmac_*"   # expect nothing
git status                                  # no stray test artifacts committed
```
Leave the engine healthy+warm or stopped cleanly — note which in the findings.

---

## Appendix — key facts

- **Version:** 0.3.145. **Engine:** `127.0.0.1:8765`.
- **Shipped MCP tools:** `map` (config `find`|`focus`), `gate`, `status`. Others
  retired.
- **Retrieval:** graph + BM25 + dense (CodeRankEmbed, 768-dim) fused; FAISS.
  Mac dense backend = **MLX (Metal)** on Apple Silicon or **CoreML/CPU**; Windows
  = DirectML.
- **Sync lanes:** hot BM25 (sub-second) + deferred graph catch-up (whole-graph
  rebuild, now batched). `focus`/graph depend on the graph lane; `find` rides the
  hot/dense lane.
- **macOS paths:** LaunchAgent `~/Library/LaunchAgents/<label>.plist`; supervisor
  log `~/Library/Logs/`; state `~/.scubiee/`; engine log `~/.scubiee/engine.log`.
- **Env knobs:** `CTX_EMBED_BACKEND` (`mlx`/`fastembed`/`cpu`/`coreml`),
  `CTX_AST_REVALIDATE_GATE_ON_EMBED` (default 1 — the cold-start gate),
  `CTX_GRAPH_CATCHUP_MAX_FILES` (default 2000 — the catch-up batch widening),
  `CTX_EAGER_PREWARM` (default 1), `CTX_ORT_SELF_HEAL` (default 1, detect-only),
  `CTX_HEALTH_REFRESHER` (default 1). In-repo runs need `PYTHONPATH=packages`;
  installed-tool runs must NOT set it.
- **DO NOT** use `packaging/uv-overrides-win-dml.txt` on macOS (Windows-only).
- **Reference:** `docs/scubiee-performance-timings.md` (Windows numbers to beat/
  match), `docs/scubiee-install-windows-dml.md` (the ORT fix pattern),
  `docs/scubiee-overview.md` (architecture).
