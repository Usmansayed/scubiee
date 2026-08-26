# Mac Cursor handoff — Scubiee pre-production (2026-08-26)

**Audience:** Cursor agent (or human) continuing work **on macOS / Apple Silicon**.  
**Repo:** `context-engine` (Scubiee).  
**Windows status:** journey P0/P1 + full non-slow pytest **green** on Windows. Mac verification is the remaining gate before treating MLX as production-proven.

---

## 1. What we are doing

Ship Scubiee so a non-CS user can:

1. Install (`uv tool install scubiee`)
2. `scubiee setup --repair` (GPU/CPU/MLX profile)
3. `scubiee init .` then `scubiee connect --<ide>`
4. Use agent MCP (`status` → `search` / `map` / `focus` / …) without wasting tokens on polling

Pre-production focus (this week):

- Fix **journey bugs** (wrong pause hint, rule “ignore forever”, `status.ok` while warming)
- Prove **Windows CPU-only** path on a real laptop (friend machine)
- Green the **Windows test suite**
- Defer **Mac / MLX** live verification to a Mac Cursor session (this doc)

Published PyPI at last friend install: **0.2.82**.  
Fixes below are **in the working tree** and intended for the next bump (**0.2.83**) — confirm version before Mac install.

Related docs:

- Full journey audit: `docs/journey-audit-pre-production-2026-08-26.md`
- Short Mac checklist (same content, condensed): `docs/macos-deferred-verification.md`

---

## 2. Context — what already happened (Windows)

### Friend laptop (UMAIR) — CPU-only Windows

| Check | Result |
|--------|--------|
| Hardware | Windows 11, Intel i5-1235U (iGPU only) |
| Profile | **`cpu`** (not DML) — correct |
| Setup | Finished ~2.6 t/s, batch 16 |
| Pain | `uv tool install --force` Access denied while supervisor held files; post-reinstall diagnose showed stale `accel.json` while `fastembed`/`onnxruntime` missing |

Canonical recovery after broken upgrade:

```text
scubiee stop
# Task Manager → end ContextEngineSupervisor if needed
Remove-Item -Recurse -Force "$env:APPDATA\uv\tools\scubiee" -ErrorAction SilentlyContinue
uv tool install --force scubiee==<ver> --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee init .
scubiee connect --cursor
```

### Journey / product fixes (done in tree)

| Priority | Issue | Fix |
|----------|--------|-----|
| P0 | Pause hint said `scubiee wake` | → `scubiee resume`; no `status` poll while paused |
| P0 | Some IDEs “ignore Scubiee forever” after one unmanaged `status()` | Event-driven retry only (anti-poll) in all rule templates |
| P1 | `status.ok: true` while `warming` / daemon down | `ok` = daemon healthy only |
| P1 | Special-4 (Kiro/Copilot/Cline/Roo) weak UX | Init + upgrade print “run connect inside each repo” |
| P1 | Windows upgrade file locks | `do_upgrade` calls `stop_all_context_engine_processes` first |
| P2 | Diagnose false confidence | Flags `stale_accel` when packages missing |

**Do not break:** token safety — never poll `status()` every turn or while paused/warming.

### Windows test suite

Last full run (dev machine):

```text
pytest tests/ -m "not slow"
→ 692 passed, 17 skipped
```

Notable env gotcha: corrupted `numpy-*.dist-info` (no `METADATA`) breaks `fastembed` imports after MCP is collected. Repair: delete broken dist-info + `pip install --force-reinstall --no-deps numpy`.

### Still open (not Mac-blocking)

- Bump / publish **0.2.83** when Mac smoke is acceptable
- Align older getting-started docs (init ≠ MCP) — P2
- Auto-rewrite MCP on upgrade (currently loud “run connect again”)

---

## 3. What Mac Cursor must do

Work from a **fresh clone or this branch** with the build under test installed. Prefer **Apple Silicon**.

### A. Install the version under test

```bash
# From repo root OR PyPI after 0.2.83 is published:
uv tool install --force scubiee==<version> --index-url https://pypi.org/simple
# OR editable from this repo:
#   uv tool install --force --from .
scubiee setup --repair
```

Record: machine model, chip (M1/M2/…), scubiee version, setup profile.

### B. Product smokes (must pass)

| # | Action | Pass criteria |
|---|--------|----------------|
| 1 | `scubiee setup --repair` | Profile **`mlx`** (not `cpu`). No hang. |
| 2 | `scubiee diagnose --no-tests --desktop` (or setup --status) | `acceleration.profile == "mlx"`; mlx / deps present |
| 3 | In a **small** git repo: `scubiee init .` | Index finishes; daemon healthy |
| 4 | `scubiee connect --cursor` | MCP + rules written |
| 5 | In Cursor agent: Scubiee `status()` | `managed: true`; when healthy, `ok: true` |
| 6 | `map` / `search` / `focus` once | Real results (not perpetual warming) |
| 7 | `scubiee stop` then `scubiee resume` | Resume works; hint must **not** say `wake` |
| 8 | Force wrong path: `scubiee setup --profile cpu` then `scubiee setup --repair` | Returns to **`mlx`** — Apple Silicon must not stay CPU-only |

Special-4 (if you use Kiro / Copilot / Cline / Roo): run `scubiee connect --<tool>` **inside that project** (workspace-local MCP).

### C. Pytest on Mac host — **use existing files; do not rewrite**

These suites already exist in the repo. **Run them as-is.** Do **not** invent a new Mac test harness, duplicate cases, or rewrite `mac_production_test.py` / CoreML / MLX modules unless a real bug fix requires a small targeted edit.

```bash
cd /path/to/context-engine
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH=packages   # if not installed editable

python -m pytest \
  tests/mac_production_test.py \
  tests/test_coreml_mac.py \
  tests/test_mlx_backend.py \
  tests/test_cross_platform_profiles.py \
  -q --tb=short
```

| Existing file | Why it needs Mac |
|---------------|------------------|
| `tests/mac_production_test.py` | Live Mac paths / permissions / multi-repo |
| `tests/test_coreml_mac.py` | CoreML / CodeRank ONNX graph checks |
| `tests/test_mlx_backend.py` | MLX embed backend |
| `tests/test_cross_platform_profiles.py` | M-series recommend `mlx` |

Optional existing live smoke (only if daemon tooling is up):

```bash
python -m pytest tests/test_mcp_locate.py::test_live_search_read_flow -q
```

### D. Behaviors to watch

1. Never demote M-series to CPU after “GPU fail” style fallbacks.
2. Warming: tools may return warming once; **do not** loop `status()` every turn.
3. After mid-session `init`, agent should re-check `status()` once (event-driven), then use MCP.
4. Prefer `scubiee stop` before `uv tool install --force` / `scubiee upgrade`.

### E. Do **not** re-prove on Mac

- Windows CPU-only / DirectML discrete GPU classifier (already live-validated)
- Windows full pytest suite (already green)
- Journey P0/P1 status/warming/template text (covered on Windows)

---

## 4. How to report back

Fill this table (also mirrored in `docs/macos-deferred-verification.md`):

| Date | Machine | Chip | scubiee version | Setup profile | Init/connect | Pytest summary | Notes / failures |
|------|---------|------|-----------------|---------------|--------------|----------------|------------------|
| | | | | | | | |

Paste any failing pytest names + first assertion line. If setup picks `cpu` on Apple Silicon, that is a **P0** for Mac — capture `accel.json` + diagnose JSON.

---

## 5. Key code map (if you need to fix Mac bugs)

| Area | Path |
|------|------|
| Accel / MLX / CPU promote | `packages/pipeline/accel.py` |
| MCP status / warming / pause | `packages/pipeline/mcp_locate.py` |
| Agent rules | `packages/pipeline/templates/context-agent.mdc` (+ legacy `.md` / `.mdc`) |
| Connect / Special-4 | `packages/pipeline/tool_registry.py`, `rules_installer.py` |
| Upgrade pre-stop | `packages/pipeline/upgrade.py` |
| Diagnose stale accel | `packages/pipeline/diagnose.py` |
| CLI | `packages/pipeline/__main__.py` |

---

## 6. Suggested Mac Cursor prompt (copy-paste)

```text
Read docs/mac-cursor-session-handoff-2026-08-26.md and execute section 3
(Mac product smokes + pytest). Run the EXISTING test files listed there
(mac_production_test, test_coreml_mac, test_mlx_backend,
test_cross_platform_profiles) — do NOT rewrite or replace them.
Record results in the table in section 4.
Do not bump/publish version unless I ask. Prefer Apple Silicon MLX path;
fail loudly if setup stays on cpu.
```
