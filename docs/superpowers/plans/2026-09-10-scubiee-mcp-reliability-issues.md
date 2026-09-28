# Scubiee MCP reliability issues (thorough audit)

**Date:** 2026-09-10  
**Version under test:** `scubiee 0.3.31`  
**Host:** Cursor (project MCP `project-0-context-engine-scubiee`)  
**Repo / project:** `C:\Users\usman\Downloads\context-engine` / `ce_2f9c289d2a885432f240969ea2889532`  
**Evidence artifacts:**
- Live Cursor session (wipe → publish → install → reconnect → locate)
- Probe JSON: [`2026-09-10-scubiee-mcp-reliability-probes.json`](./2026-09-10-scubiee-mcp-reliability-probes.json)
- Probe script: [`scripts/scubiee_mcp_reliability_audit.py`](../../../scripts/scubiee_mcp_reliability_audit.py)

**Goal of this doc:** inventory every reliability failure we hit or reproduced so we can design fixes. Not a patch list yet — each issue ends with a *solution direction* to debate.

---

## Executive summary

Locate quality is **good when warm** (map → pack consistently hits the right seeds). Reliability of *getting and staying warm* is the problem.

Agents feel MCP as “unreliable” because:

1. Engine / index flaps during setup, indexing, and idle sweep.
2. `status` readiness vocabulary contradicts itself (`warm_state=ready` vs `soft_search_ready=false` vs `agent_ready=warming`).
3. Cursor MCP host connection dies after process kills / upgrades and does not self-heal.
4. Happy-path latency is high (status ~18s, map ~18s, pack ~24s in stdio probe).
5. Failure modes often return empty/`warming`/tracebacks instead of one actionable repair command.

**Probe score (automated):** 9 pass / 2 fail (+ 10 catalogued session issues).  
**Live Cursor score (subjective):** locate **9/10** when healthy; end-to-end reliability **~4/10** after wipe/reinstall.

---

## Severity legend

| Sev | Meaning |
|-----|---------|
| **P0** | Blocks agents from using MCP locate in normal workflows |
| **P1** | Frequent false negatives / thrash; recoverable with manual steps |
| **P2** | Confusing signals / latency / polish that cause wrong agent behavior |

---

## Issue catalog

### P0 — IDLE-SWEEP-KILLS-INDEX

**Symptom:** While indexing / rebuilding, engine log shows:

```text
[engine] idle sweep: action=standby ...
[engine] idle sweep: retiring self (external stop cannot kill the engine's own pid)
```

Health then flaps `indexing` ↔ connection refused. Rebuild aborts mid-flight.

**Repro:**
1. Default Cursor MCP env uses `CTX_ENGINE_IDLE_S=15` (`packages/pipeline/mcp_install.py`).
2. `scubiee rebuild .` or post-wipe indexing.
3. Only `/health` traffic (treated as passive) → idle sweeper retires daemon.

**Evidence:** `~/.scubiee/engine.log` during first rebuild attempt; indexing never reached `index_usable=true` until idle raised to `3600` and rebuild rerun.

**Why it hurts:** Agents see endless `warming` / `WinError 10061` and give up or shotgun Grep.

**Solution direction:**
- Do **not** idle-stop while `warm_state in {warming,indexing}` or any index lock held.
- Treat active index / embed / publish work as a client hold.
- Raise default MCP idle (e.g. 300–900s) or disable idle while `CTX_AUTO_INDEX=1`.
- `/health` alone should not be the only keepalive — but work-in-progress must veto standby.

---

### P0 — MAP-WINERROR-10061-RACE

**Symptom:** Cursor `map` returns:

```text
Scubiee unreachable at http://127.0.0.1:8765: [WinError 10061] ...
```

while a simultaneous shell `GET /health` sometimes succeeds (or succeeds 1s later).

**Repro:** Call MCP `map` during indexing / idle-retire flaps.

**Evidence:** Repeated in this Cursor session before rebuild completed.

**Solution direction:**
- Bridge should auto-`engine ensure` / wake-on-demand with bounded wait (e.g. 5–15s) before surfacing unreachable.
- Distinguish `starting` vs `dead` vs `idle-standby` in error payload with `repair: ["scubiee engine ensure <root>"]`.
- Singleflight wake so parallel MCP tools don’t stampede.

---

### P0 — WARM-ERROR-DML-PROVIDER

**Symptom:** After wipe/reinstall:

```json
"warm_state": "error",
"warm_error": "Scubiee required dependencies unavailable: provider:DmlExecutionProvider..."
```

`map` → `{"error":"warming", ...}` even though status says `should_use_mcp: true`.

**Repro:** Wipe install → `uv tool install scubiee==0.3.31` → start engine without re-running `scubiee setup` (or after accel profile drift).

**Evidence:** Live `status` before `scubiee setup` repaired DML; setup ended `Ready (dml)`.

**Solution direction:**
- On first engine start after tool install, auto-run accel verify / setup repair (or block with one crisp `repair` field).
- Stop classifying hard accel failure as `warming` — use `warm_state=error` + non-retryable flag so agents don’t loop `status`.
- `should_retry_status` / `should_use_mcp` should go false when `warm_error` is dependency-missing.

---

### P0 — CORRUPT-PUBLICATION-CHECKSUM

**Symptom:** `scubiee doctor` repair plan:

```text
corrupt publication (checksum_mismatch) — rebuild index
```

Soft search stuck / flapping until `scubiee rebuild .` (successful rebuild: 6221 chunks in ~80s).

**Repro:** Wipe + partial indexes + idle kills mid-publish (likely).

**Evidence:** doctor output; rebuild JSON `rebuilt: true, chunks: 6221`.

**Solution direction:**
- Detect checksum mismatch at engine open and **auto-rebuild** (or auto-quarantine + rebuild) instead of serving half-ready state.
- Make publish atomic (temp → rename) so idle kill can’t leave corrupt publication.
- Surface `repair: ["scubiee rebuild <root>"]` on map/status when checksum fails.

---

### P0 — MCP-HOST-DISCONNECT-AFTER-KILL

**Symptom:** After killing `scubiee-mcp` / `scubiee-mcp-bridge` (needed for `uv tool install --force` file locks):

- Cursor namespace missing or `namespaceStatus=error`
- Tool calls: `Not connected` / `MCP server does not exist: scubiee`
- Only `mcp_auth` stub until user reloads MCP / re-auths

**Repro:** Upgrade/reinstall while Cursor has MCP attached.

**Evidence:** This session after 0.3.31 install.

**Solution direction:**
- Document + automate: `scubiee unlock-tool` / stop MCP before tool replace; restart bridge after.
- Prefer in-place upgrade that doesn’t require deleting locked `Scripts/`.
- Cursor-side: reconnect MCP automatically after bridge exit (host limitation — may need bridge supervisor).
- Ship a `scubiee upgrade` that coordinates unlock → install → reconnect.

---

### P0 — MCP-STDIO-BURST / EMPTY -32603

**Symptom:** Stdio probe happy-path `initialize → status → map → pack → expand` works; then burst `map×5` dies with:

```json
{"code": -32603, "message": ""}
```

**Repro:** `scripts/scubiee_mcp_reliability_audit.py` (see probe `mcp_stdio_session`).

**Evidence:** Probe JSON fail entry; expand succeeded (64ms) then session error.

**Solution direction:**
- Never return empty `-32603`; always include exception type + repair hint.
- Investigate bridge crash / pipe close under serial tool pressure.
- Add regression test: N serial maps over one stdio session.

---

### P1 — STATUS-SOFT-SEARCH-UNBOUND

**Symptom:** Conflicting readiness:

| Field | Observed |
|-------|----------|
| `engine.warm_state` | `ready` |
| `engine.soft_search_ready` | `false` |
| `engine.project_id` | `null` |
| `index_available` | `false` |
| `agent_ready` | `warming` |
| `ready` | `false` |
| HTTP `/health` | `warm_state=ready`, `index_usable=true` |

Yet **MCP `map` can still succeed** with good cards (observed live).

**Repro:** After rebuild / engine restart without `scubiee engine ensure <repo>`; or MCP session whose bound project drifted.

**Evidence:** Multiple live `status` cards in this chat; map still returned `write_project_gate_rules`.

**Why it hurts:** Agents obey `agent_ready=warming` / `ready=false` and refuse to locate even when map works — *or* they ignore status and thrash.

**Solution direction:**
- Auto-bind `CTX_REPO` / `project_id` on every locate tool entry (`map`/`pack`) — don’t require separate ensure.
- Unify readiness: one enum `locate_ready | starting | indexing | error | unbound` with single `repair[]`.
- If map works, `soft_search_ready` must not be false (bug).

---

### P1 — COLD-WAKE-MAP-RACE

**Symptom:** Immediately after `scubiee engine start`, map fails while health shows `warm_state=indexing` / `index_usable=false`. CLI may dump a **traceback** instead of structured error.

**Repro:** Probe `cli_map_immediately_after_engine_start` (FAIL).

**Solution direction:**
- Wake path should wait for `index_usable` with progress, or return structured `{error:"indexing", retry_after_s, progress}`.
- CLI must never traceback on expected not-ready states (JSON error always).
- MCP `map` should optionally block up to N seconds for indexing completion when generation is catching up.

---

### P1 — CLI-MAP-TRACEBACK-ON-ENGINE-DOWN

**Symptom:** With engine stopped, `scubiee map …` exits with Python traceback (`probe cli_map_when_engine_stopped` marked pass only because “error-ish” text appeared — UX still bad).

**Solution direction:** Catch daemon-down at CLI boundary; print compact JSON `{ok:false, error:"engine_down", repair:[...]}` and exit 2.

---

### P1 — PYPI-INSTALL-FILE-LOCK

**Symptom:**

```text
error: failed to remove directory ...\uv\tools\scubiee\Scripts: Access is denied. (os error 5)
```

Leaves trampoline broken (`ModuleNotFoundError: pipeline`) until processes killed + reinstall.

**Repro:** `uv tool install --force scubiee==0.3.31` while Cursor MCP holds the env.

**Solution direction:**
- `scubiee unlock-tool` / `scubiee upgrade` stops bridge + engine cleanly before uv replace.
- Teach wipe/reinstall docs to always unlock first.
- Consider user-level install path that doesn’t lock Cursor-attached interpreters (hard on Windows).

---

### P1 — DEFAULT-IDLE-15-IN-CONNECT

**Symptom:** Product default in `mcp_install.py`:

```python
"CTX_ENGINE_IDLE_S": "15",
```

This is aggressive for indexing + agent think-time between tools.

**Note:** During this audit we temporarily set live `.cursor/mcp.json` to `3600` to finish rebuild. Fresh `scubiee connect` will write `15` again unless changed in product.

**Solution direction:** Change default to ≥300s for IDE MCP; keep short idle only for headless CI profiles.

---

### P2 — AGENT-READY-VOCAB-CONFUSING

**Symptom:** Too many parallel signals:

- `warm` / `warm_state` / `warm_error`
- `soft_search_ready` / `index_available` / `index_usable`
- `ready` / `agent_ready` (`warming`|`stale`|…) / `agent_ready_note`
- `sync_state` / `syncing` / `overlay_ready`
- `should_use_mcp` / `should_retry_status` / `warming`

Example (healthy-ish engine, agent told to wait):

```json
"agent_ready": "warming",
"ready": false,
"engine": {"soft_search_ready": false, "warm_state": "ready", "project_id": null}
```

Earlier full status also showed `agent_ready=stale` while soft search was true and syncing.

**Solution direction:**
- Collapse to one agent-facing field: `locate: {state, reason, repair[]}`.
- Keep detailed engine fields under `engine` for humans/doctors only.
- Update GATE / MCP instructions to key off the single field.

---

### P2 — STATUS-TTL-STALE-AFTER-FLAP

**Symptom:** MCP returns cached status (`status_ttl_s: 300`) while engine already refused connections; agents trust stale “ok” card.

**Evidence:** `map` unreachable with prior status still within TTL.

**Solution direction:**
- Invalidate status cache on transport errors.
- Short TTL while `warm_state != ready` or last map failed.
- Include `engine_pid` / `generation` so agents can detect flaps.

---

### P2 — HAPPY-PATH-LATENCY

**Symptom (stdio probe, already warm):**

| Call | Latency |
|------|--------:|
| `status` (full) | ~17.9s |
| `map` | ~18.0s |
| `pack_context` lean | ~24.1s |
| `expand_context` | ~0.06s |

**Why it hurts:** Feels hung; agents parallelize or abandon ladder; exceeds human patience.

**Solution direction:**
- Profile status full (keeper dump?) — default summary must be <<1s.
- Keep map/pack warm-path under a few seconds when index ready.
- Stream progress / return `retry_after` instead of blocking silently.

---

### P2 — HEALTH-VS-WARM-FLAG

**Symptom:** `/health` often returns `"warm": false` while `"warm_state": "ready"` and `"index_usable": true`.

**Solution direction:** Align boolean `warm` with `warm_state==ready && index_usable` or deprecate the boolean.

---

## What worked (keep)

| Area | Result |
|------|--------|
| MCP tool surface (ship) | `gate/map/pack_context/expand_context/collect_hot_context/workspace/expand/status` present |
| Map ranking (when ready) | Correct seeds: `write_project_gate_rules`, `apply_permissions_to_repo_tool_surface`, `write_cursor_mcp` |
| Pack lean heatmap | Tight cluster around gate writers |
| Expand | Fast delta once pack existed |
| Setup repair | `scubiee setup` restored DML after wipe |
| Rebuild | Full reindex ~80s wall for ~6.2k chunks once idle didn’t kill it |
| GATE MCP-first text | Live rules BAN shell locate while MCP callable |

---

## Recommended fix order (for later implementation)

**Status (2026-09-10):** **scubiee 0.3.32** published + installed — reliability fixes live. Reload Scubiee MCP in Cursor after connect. Latency stretch (#7) only partially (cheap `status` summary).

1. **Idle veto while indexing + safer default idle** (stops flaps / corrupt publish). ✅  
2. **Atomic publish + auto-rebuild on checksum mismatch**. ✅  
3. **Wake-on-demand in MCP bridge** with structured errors (kills 10061 thrash). ✅ (locate path)  
4. **Unify readiness API** (`locate.state` + `repair[]`); fix unbound soft-search lying. ✅  
5. **Accel/setup gate** after install (no fake `warming` on missing DML). ✅  
6. **Upgrade/unlock path** so Windows tool replace doesn’t break Cursor MCP. ✅ (pre-prepare)  
7. **Latency pass** on `status`/`map`/`pack` warm path. ◐ status summary only  
8. **Clean CLI/MCP errors** (no traceback, no empty -32603). ✅

---

## Re-run audit

```powershell
cd C:\Users\usman\Downloads\context-engine
$env:CTX_ENGINE_IDLE_S = '3600'
scubiee engine ensure .
& "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe" scripts\scubiee_mcp_reliability_audit.py
```

Then compare `docs/superpowers/plans/2026-09-10-scubiee-mcp-reliability-probes.json`.

---

## Appendix A — Live Cursor timeline (this session)

1. MCP missing / auth-only after reinstall.  
2. `status`: DML `warm_error`; `map` → `warming`.  
3. `scubiee setup` → Ready (dml).  
4. Engine idle-swept during indexing; `map` → 10061.  
5. `doctor` → checksum_mismatch.  
6. Rebuild #1 killed by idle sweep.  
7. Idle raised → rebuild #2 OK (6221 chunks).  
8. `engine ensure` → HTTP ready.  
9. Cursor MCP `Not connected` until reload/`mcp_auth`.  
10. `status` still showed unbound/warming; **`map`/`pack` succeeded** with correct seeds.

---

## Appendix B — Probe table

| Probe | Result | Notes |
|-------|--------|-------|
| http_health_baseline | PASS | ready + usable |
| cursor_mcp_idle_default_is_aggressive | PASS* | live file was already raised to 3600; **product default still 15** |
| mcp_initialize | PASS | 2.5s |
| mcp_tools_list | PASS | ship tools present |
| mcp_status_signal_coherence | PASS* | probe logic too weak; live unbound issue still real |
| mcp_map_happy | PASS | ~18s |
| mcp_pack_lean_happy | PASS | ~24s |
| mcp_expand_context | PASS | ~64ms |
| mcp_stdio_session (burst) | FAIL | empty -32603 |
| cli_map_when_engine_stopped | PASS* | errors, but via traceback |
| cli_map_immediately_after_engine_start | FAIL | cold-wake race |

\*See issue text — “pass” does not mean UX is good.
