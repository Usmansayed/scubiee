# CE Self-Manageable Production Design

**Date:** 2026-08-18  
**Branch:** `feat/production-certification`  
**Status:** Approved for this session (user: write gaps, then fix in one run)

## What “production ready” means here

Context Engine is production-ready when an operator (or `ctx doctor --fix`) can
**diagnose, apply safe repairs, and certify** without copy-pasting tribal CLI,
and without silent degraded search.

This is **not** a new product surface. Graph stays bounded. External IDE
clients stay opt-in. Destructive actions (rebuild, Forget, `init --repair`,
pip installs) stay explicit.

## Evidence from this tree (before the fix)

| Gate | Result |
|------|--------|
| `python -m pipeline certify . --skip-daemon` | `ok: true`, `failed_required: 0` |
| `python -m pipeline doctor .` | `ok: false` — daemon bound to main checkout, this worktree unbound |
| Advertised repair | `ctx engine ensure <worktree>` — **doctor does not apply it** |
| Dashboard Health | read-only dump of `doctor_report()` (accel only) |
| `test core` | omits dashboard API/UI tests |

## Pending gaps (must fix)

### 1. Safe repairs are advice, not actions

Doctor prints `repairs[]`. There is no `doctor --fix`. Dashboard Health has no
Apply control. The live failure (wrong daemon bind) is exactly the class of
problem the product already knows how to fix via `ensure_daemon` → `open_repo`.

**Required:** classify every repair as `safe` or `manual`. `--fix` and
`POST /ce-dashboard/api/repair` apply **only** `safe` actions, then re-doctor.

Safe:

- `bind_daemon` — `ensure_daemon(repo)` so the running engine binds this path
- `initialize_index` — `initialize_repo(root, index=True)` when the store is
  not usable and the publication manifest is not corrupt
- `replay_dirty_journal` — restore journal then `sync_now_repo`

Manual (print, never auto-apply):

- missing Python packages / parser wheels
- `python -m pipeline init --repair` (accel/provider/model)
- corrupt publication manifest → rebuild
- Forget / clear-index / never-index

### 2. Fleet diagnosis is missing

`doctor` is one repo. Operators managing several checkouts cannot see which
ones are unbound or unusable.

**Required:** `doctor --all` and dashboard Health list every managed
repository’s `ok`, `repairs`, and `kind`.

### 3. Dashboard Health cannot repair

Health GET uses accel-only `doctor_report()`. Mutations from a
`http://localhost:<port>` Origin are rejected against a `127.0.0.1` server
origin, so a browser opened via localhost cannot apply settings or repairs.

**Required:**

- Health payload includes fleet doctor + classified repairs
- `POST /ce-dashboard/api/repair` applies safe repairs (one repo or all)
- Treat `localhost` / `127.0.0.1` / `::1` as the same loopback host when the
  port and scheme match
- Health UI shows repairs and an **Apply safe repairs** button

### 4. Core certification omits the operator dashboard

`pipeline.test_runner` core/fault tiers do not include dashboard tests. A
green `ctx test core` can hide a broken operator console.

**Required:** add the dashboard suite to the `core` (and therefore
certification) tier. Certify must include a sandboxed `apply_safe_repairs`
scenario.

### 5. Stale operator copy

CLI `settings` and `setup` still point at `http://127.0.0.1:8765/dashboard`.
The operator UI is `ctx dashboard` → `http://127.0.0.1:<ephemeral>/ce-dashboard`.

**Required:** fix those strings. Runbook documents `doctor --fix`.

## Explicitly out of scope

- Graph explorer expansion
- Auto `pip install` / auto `init --repair`
- Auto rebuild on corrupt manifests
- Sleep/wake and real disk-full labs
- External client matrix (`ctx test clients --clients`)
- Rebinding the user’s live daemon as a side effect of unit tests

## Success

1. `python -m pipeline certify . --skip-daemon` → `ok: true`
2. `python -m pipeline test core` → `ok: true`
3. Dashboard + doctor unit tests prove `--fix` applies bind/initialize and
   leaves package/accel repairs manual
4. `localhost` Origin mutations succeed against `127.0.0.1` server origin
5. Operator runbook matches the CLI that actually exists
