# CE Production Hardening Release — Design

**Date:** 2026-08-17  
**Branch / worktree:** `feat/ce-dashboard` / `.worktrees/ce-dashboard`  
**Status:** Approved in conversation (finish existing scope; Graph keep-as-is; main path must be reliable)

## Problem

Context Engine already has production certification, live reindexing, and an operator dashboard (Tasks 1–5 committed; Task 6 Graph + UI polish present but uncommitted). The product is not yet “complete for production” because:

1. Graph API/UI and UI polish are uncommitted.
2. One UI contract test fails after CSS token renames (`--surface:`).
3. Operators cannot treat the worktree as a finished install: `ctx dashboard` is not verified from an installable package path.
4. Reliability evidence for the main operator path (start / status / stop / overview / repos / lifecycle / settings / health) is incomplete relative to a production claim.

## Goals

1. Ship a **production-ready operator shell** that is autonomous on localhost and safe under restart.
2. Keep Graph as a **bounded, already-working** read-only feature — no further Graph visualization development.
3. Make the **main operator path completely reliable**: dashboard process control, presence/lifecycle, admission settings, health/runtime/storage/sync, and static UI contracts.
4. Leave a clear release gate: tests green, smoke commands succeed, runbook accurate, branch reviewable/PR-ready.

## Non-goals

- Expanding Graph into a full interactive explorer (force layout, search, hop tools).
- Cloud auth, multi-user access, LAN exposure.
- New indexing algorithms or retrieval architecture.
- Guaranteeing GPU acceleration beyond existing verified-provider-or-CPU-safe policy.
- Merging unrelated dirty work from other branches into this release.

## Scope decisions

### Graph (keep, do not grow)

- Keep `GET /ce-dashboard/api/graph/{id}` read-only against existing Graphify `graph.json`.
- Keep UI: repository picker, counts, SVG ≤60 nodes, links list ≤100, empty/error states, accurate truncation copy.
- Graph is nice-to-have for operators; **release reliability does not depend on Graph polish**.

### Main reliability path (must pass)

| Surface | Reliability bar |
|---------|-----------------|
| Dashboard process | Start/reuse, `--status`, `stop`, loopback-only bind, private port persistence, safe PID ownership on stop |
| Overview / repos / sync | Correct managed list and presence states; no synthetic storage fields |
| Lifecycle | Unmanage / clear-index / locate / forget only after validation + typed confirm |
| Settings | Automatic vs Manual (`mcp_cli`) admission persists and reloads |
| Health / runtime / storage | Serve real doctor/runtime/storage payloads; UI does not invent fields |
| Static UI | Contract tests pass for shell, assets, Lucide allowlist, light theme tokens |
| Install usability | Documented commands work from the worktree with `PYTHONPATH=packages` / editable install notes |

## Architecture

No new services. Harden and finish what exists:

```
ctx / python -m pipeline dashboard
        │
        ▼
dashboard_port + dashboard.json lock
        │
        ▼
loopback HTTP (/ce-dashboard)
  ├── static UI (HTML/CSS/JS + lucide.min.js)
  └── JSON API wrapping repo_lifecycle, presence,
      doctor, runtime, storage_policy, settings,
      and read-only graph.json
```

Reliability rules that stay binding:

- Bind `127.0.0.1` only; base path `/ce-dashboard`; ports `49152–65535`.
- Missing ≠ deleted; Forget requires eligibility + typed `project_id`.
- Stop must prove PID ownership before kill.
- Mutating APIs refuse non-loopback clients.
- Reuse existing lifecycle/doctor/storage modules; do not reimplement indexing.

## Workstreams

### W1 — Stabilize current uncommitted surface

- Fix UI contract for CSS tokens (either restore expected tokens or update contracts to match intentional shadcn/zinc tokens).
- Ensure Lucide asset is allowlisted and served.
- Keep Graph API/UI as implemented; only fix clear correctness bugs if regression fails.

### W2 — Reliability regression

- Run full dashboard suite: port, presence, lifecycle actions, API, UI contract.
- Smoke: `dashboard --no-open`, `--status`, overview/repos/health curl, Graph smoke if artifact present, `dashboard stop`.
- Confirm process does not leave orphan PIDs and restart reuses lock correctly.

### W3 — Operator docs + release evidence

- Runbook already documents dashboard start/status/stop, Missing vs Forget, Auto vs Manual — verify and tighten if wrong.
- Record release checklist results in SDD ledger / short release note (not marketing docs).

### W4 — Finish branch

- Commit Task 6 + polish + reliability fixes with clear messages.
- Whole-branch review against dashboard + production-certification expectations.
- Leave branch PR-ready; install/editable-install instructions for global `ctx dashboard`.

## Testing strategy

1. Focused fix for failing UI contract.
2. Graph API unit/API test remains green.
3. Full dashboard regression suite green.
4. Manual/scripted smoke: start → status → key APIs → stop.
5. Optional: `pip install -e .` from worktree and verify `ctx dashboard --status` if packaging already exposes the command.

## Success criteria

- [ ] No failing dashboard tests in the required regression set.
- [ ] Dashboard start/status/stop cycle is deterministic and loopback-only.
- [ ] Core pages load without invented API fields or unsafe delete affordances.
- [ ] Graph remains available as read-only; no new Graph scope creep.
- [ ] Changes committed on `feat/ce-dashboard`; ledger updated; branch ready for PR.

## Out of release if they appear

- Slow overview API under heavy doctor/accel probing — mitigate only if smoke fails or hangs; do not redesign doctor.
- Cross-platform GPU claims beyond existing certification policy.
- React/Vite rewrite of the static dashboard.
