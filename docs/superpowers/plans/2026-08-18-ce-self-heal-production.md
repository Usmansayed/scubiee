# CE Self-Heal Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline in this session).

**Goal:** Make Context Engine diagnose and apply safe repairs from CLI and dashboard, then prove it with core tests and certify.

**Architecture:** Extend `doctor.py` with classified repair plans and `apply_safe_repairs`. Wire `--fix`/`--all` on the CLI and `/api/repair` on the dashboard. Origin matching treats loopback aliases as same-origin. Core test tier includes dashboard tests.

**Tech Stack:** Python 3.13, pytest, existing dashboard static UI.

## Global Constraints

- Safe repairs never pip-install, never `init --repair`, never Forget, never rebuild on corrupt manifests.
- Unit tests mock `ensure_daemon` / `initialize_repo`; they must not rebind the live engine.
- Dashboard remains loopback-only on `/ce-dashboard`.
- Graph UI stays bounded as already shipped.

---

### Task 1: Doctor repair plan + apply

**Files:**

- Modify: `packages/pipeline/doctor.py`
- Modify: `tests/test_doctor_certify.py`
- Modify: `packages/pipeline/__main__.py`
- Modify: `packages/pipeline/certify.py`

**Produces:** `plan_repairs`, `apply_safe_repairs`, `doctor_all`

### Task 2: Dashboard repair API + localhost origin

**Files:**

- Modify: `packages/pipeline/dashboard_server.py`
- Modify: `tests/test_dashboard_api.py`

### Task 3: Health UI Apply control

**Files:**

- Modify: `packages/pipeline/dashboard_ui/app.js`
- Modify: `packages/pipeline/dashboard_ui/index.html`
- Modify: `tests/test_dashboard_ui_contract.py`

### Task 4: Core gate includes dashboard + copy fixes

**Files:**

- Modify: `packages/pipeline/test_runner.py`
- Modify: `tests/test_test_runner.py`
- Modify: `packages/pipeline/__main__.py` (settings/setup copy)
- Modify: `docs/reindexing/production-operator-runbook.md`
