# Indexing & projects

How Scubiee decides **what** to index, **when** to ask for confirmation, and **where** project data is stored.

---

## Project identity

Each managed repository gets a stable **`project_id`** (e.g. `ce_ab9a0c9170ecd47c9164108742ffca29`).

| File / dir | Role |
|------------|------|
| `<repo>/.scubiee/id.json` | Binds this folder to `project_id` |
| `~/.scubiee/registry.json` | Lists all managed roots and lifecycle state |
| `~/.scubiee/projects/<project_id>/` | Index store (chunks, graph, FAISS, merkle) |

Git worktrees that share the same git common dir can share one project id across related paths — that is intentional.

If you move a repo: the id file travels with it. If you delete the id file but registry still knows the path, Scubiee can recover. If both are gone, a **new** id is created and a **re-index** is required.

---

## What gets indexed

Default full index walks the repo with skip rules (vendor, `node_modules`, `.git`, large test corpora like `testdata/` in many layouts, etc.). The exact skip list is in the product’s path policy — **not every file on disk is counted or indexed**.

**Fast mode** (`--fast`):

- Only **`.py`** files
- Only under common code roots: `packages`, `src`, `lib`, `app`, `tests`, … (or your `--roots` list)

Example:

```bash
scubiee init . --fast --roots packages
```

Use fast mode for a first run on large monorepos.

---

## Before first `init`

`scubiee init` requires a completed machine setup. If `accel.json` is missing:

```json
{"ok": false, "error": "machine_not_setup", "repair": "python -m pipeline setup"}
```

**Fix:**

```bash
scubiee setup --repair
scubiee init . --fast
```

---

## Safety: home directory and drive roots

Scubiee **refuses silent indexing** of:

- Your **user home directory** (`C:\Users\you` or `/Users/you`)
- **Drive root** on Windows (`C:\`)
- **Filesystem root** on Unix (`/`)

Example error:

```json
{
  "ok": false,
  "error": "Refusing to index C:\\Users\\usman (user home directory). Change into your project directory and run `scubiee init`, or re-run with --confirm if you really want to index here.",
  "needs_confirm": true
}
```

**Fix:** `cd` into your project, then:

```bash
scubiee init .
```

Do **not** run bare `scubiee init` from your home folder expecting it to index “the current project” — it uses the **current directory** as the root.

If you truly need to index a broad path (rare):

```bash
scubiee init /very/large/path --confirm
```

---

## Safety: >400 file confirm gate

Before a large index or sync, Scubiee counts **indexable** files (same rules as actual indexing — not raw `find` counts).

If more than **400** files would be touched (default), it stops and asks for explicit consent:

```json
{
  "ok": false,
  "needs_confirm": true,
  "n_files": 539,
  "error": "539 files need indexing (>400). Re-run with --confirm ..."
}
```

**Fix:**

```bash
scubiee init . --confirm
# or
scubiee index . --confirm
scubiee sync . --confirm
```

Override cap (power users):

```bash
set CTX_INCREMENTAL_MAX_TOUCH=800
```

`--force` on index bypasses the confirm gate for full re-indexs; prefer `--confirm` for clarity.

---

## Never-index

Permanently block indexing for a path (shared git-family projects):

```bash
scubiee never-index . --reason "operator choice"
```

After never-index, `init` / `sync` return `"error": "never_index"`. Remove via lifecycle/dashboard forget flows or registry edit (advanced).

---

## Stale or wrong home registration

If you accidentally registered **`C:\Users\you`** or your home folder earlier:

1. List repos: `scubiee list`
2. Remove: `scubiee remove C:\Users\you --delete-store`
3. Delete leftover identity if present: `C:\Users\you\.scubiee\id.json`

Symptoms of stale home registration:

- `certify` fails with `project_id_mismatch`
- `doctor --all` fails on multi-repo tests
- Daemon tries to reconcile your home folder on startup

---

## Incremental sync vs full index

| Operation | Scope |
|-----------|--------|
| `scubiee sync .` | Files changed since last merkle/git snapshot |
| `scubiee sync-now .` | Lifecycle reconciliation |
| `scubiee rebuild .` | Full rebuild (slow) |
| `scubiee index . --force` | Force full index pipeline |

After `git pull`, run `scubiee sync .`. In Cursor automatic mode, the keeper syncs on a timer when files change.

---

## Pause / resume

```bash
scubiee pause . --reason "release week"
scubiee resume .
```

Paused repos stay registered but background indexing stops.

---

## Related

- [Getting started](./getting-started.md)
- [Daily use](./daily-use.md)
- [Troubleshooting](./troubleshooting.md#project_id_mismatch--stale-home-registration)
