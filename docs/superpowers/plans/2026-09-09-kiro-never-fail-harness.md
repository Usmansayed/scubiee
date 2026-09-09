# Never-Fail Kiro Harness Implementation Plan

> **For agentic workers:** Implement Gates 0–5 from `out/harness_never_fail_design.md` (Kiro Sonnet 5 design ask, 2026-09-09) plus hard-abort policy chosen by the user. Primary file: `scripts/kiro_mcp_ab_dev_eval.py`.

**Owner choice (2026-09-09):** `1` hard abort **+ ask agent**. Gate A design delivered at `out/harness_never_fail_design.md` (3.11 credits).

**Goal:** Never burn Sonnet credits on a cold/broken snapshot; never score uncallable-fallback as skip-pack.

**Architecture:** Gates 0–2 free/deterministic → Gate 3 AI preflight (strict payload ok) → Gate 4 expensive job only if all prior pass → Gate 5 taxonomy labels (ladder × retrieval).

## File map

| File | Role |
|---|---|
| `scripts/kiro_mcp_ab_dev_eval.py` | All gate logic, scoring, abort |
| `out/harness_never_fail_design.md` | Spec from Kiro (source of truth for predicates) |
| `out/harness_design_ask.md` | Prompt used for Gate A |
| `docs/superpowers/plans/2026-09-09-kiro-never-fail-harness.md` | This plan |
| `tests/test_ab_eval_taxonomy.py` | Taxonomy / CLI-leak unit locks |

## Tasks

### Task 1: Deterministic warm proof (Gate 2) — DONE

`deterministic_warm_proof(ws)` + `--warm-proof-only`. PASS only on map/pack payloads.

### Task 2: Wire hard abort before Sonnet job — DONE

`run_arm` aborts with `arm_status: warm_proof_failed` (no chat). No preflight shortcut.

### Task 3: Strict AI preflight ok — DONE

map+pack payload `ok` required.

### Task 4: Ladder taxonomy scoring — DONE

`uncallable_fallback` / `skip_pack_violation` / `ladder_ok` (+ unit tests).

### Task 5: Smoke + Kiro diffs — DONE

`--gate-smoke`, `assert_project_id_binding`, `arm_status` enum, taxonomy tests.

### Smoke

```powershell
python scripts/kiro_mcp_ab_dev_eval.py --check-surface
python scripts/kiro_mcp_ab_dev_eval.py --warm-proof-only
python scripts/kiro_mcp_ab_dev_eval.py --gate-smoke
python -m pytest -q tests/test_ab_eval_taxonomy.py
```
