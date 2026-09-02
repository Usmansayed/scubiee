# Repository lifecycle

How Scubiee **enrolls**, **pauses**, **activates**, **removes**, and **wipes** a repository — and what data is kept or deleted at each step.

**Docs assume [scubiee 0.3.14](https://pypi.org/project/scubiee/0.3.14/)** (published on PyPI).

---

## States a repo can be in

| State | Meaning | Typical next step |
|-------|---------|-------------------|
| **unmanaged** | Never initialized, or fully wiped/removed | `scubiee init .` |
| **managed / active** | Enrolled, indexed, background sync may run | Normal daily use |
| **paused** | Still enrolled; indexing/sync blocked for this repo | `scubiee activate .` |
| **never-index** | Path permanently refused for indexing | Remove block or use another folder |

Check anytime:

```bash
scubiee status .
```

Uninitialized folders show `enrolled: false` and `state: "unmanaged"`.

---

## Command cheat sheet

| Goal | Command |
|------|---------|
| Enroll + index | `scubiee init .` |
| Enroll without indexing | `scubiee init . --no-index` |
| Pause background work (keep data) | `scubiee pause .` |
| Resume paused repo | `scubiee activate .` |
| Unmanage + **delete all repo Scubiee data** | `scubiee wipe . --confirm` |
| Unmanage registry only (optional store delete) | `scubiee remove .` or `scubiee remove . --delete-store` |
| Block indexing forever | `scubiee never-index . --reason "…"` |
| List all managed repos | `scubiee list` |
| Stop engine globally (all repos) | `scubiee stop` → `scubiee resume` |

---

## Pause vs stop vs wipe (important)

These are **not** interchangeable.

### Per-repo pause — `scubiee pause .`

- Stops background indexing/sync for **this repo only**
- **Keeps** enrollment, index store, VectorDB, `.scubiee/id.json`
- `sync-now` is blocked until you **`scubiee activate .`**
- Other repos continue normally

### Global stop — `scubiee stop`

- Stops the engine and tears down MCP/rules surfaces machine-wide
- **Keeps** all repo data on disk
- Most CLI/MCP blocked until **`scubiee resume`**
- Use before upgrade, uninstall, or when Windows file locks appear

### Repo wipe — `scubiee wipe . --confirm`

- **Unmanages** the repo and **deletes** its Scubiee-owned data
- Does **not** delete your source code
- Does **not** uninstall Scubiee or wipe other repos
- Global MCP (e.g. user `~/.cursor/mcp.json`) stays — other projects keep working

---

## Unmanage one repo and delete its data (recommended)

From the project root:

```bash
cd /path/to/your/repo
scubiee wipe . --confirm
```

Or from anywhere:

```bash
scubiee wipe /path/to/your/repo --confirm
```

In a TTY you can omit `--confirm` and answer the prompt. Without confirmation, exit code is **2** and nothing is deleted.

### What a single-repo wipe removes

| Removed | Location / notes |
|---------|------------------|
| Registry enrollment | `~/.scubiee/registry.json` — repo becomes **unmanaged** |
| Index store | `~/.scubiee/projects/<project_id>/` |
| VectorDB collections | Collections tied to this repo cwd |
| Repo identity folder | `<repo>/.scubiee/` (and nested copies if any) |
| Legacy index paths | Old `~/.scubiee/indexes/…` if present |
| Project MCP pins + GATE rules | e.g. `.cursor/mcp.json`, agent rule files under this repo |

### What a single-repo wipe keeps

| Kept | Why |
|------|-----|
| Your source files | Wipe never deletes project code |
| Other enrolled repos | Scope is one path |
| User-global MCP config | Cursor global `mcp.json` from `connect` |
| `accel.json`, model caches, GPU runtime | Machine-level; shared across repos |
| Scubiee package install | Use `wipe --all --confirm --package` to uninstall |

After wipe, re-enroll with:

```bash
scubiee init .
scubiee connect --cursor    # if using Cursor
```

---

## `remove` vs `wipe`

| | `scubiee remove [path]` | `scubiee wipe [path] --confirm` |
|--|-------------------------|----------------------------------|
| Unmanage registry | Yes | Yes |
| Delete index store | Only with `--delete-store` | Yes (always) |
| Drop VectorDB | No | Yes |
| Remove `.scubiee/` in repo | No | Yes |
| Strip repo MCP/rules | No | Yes (via wipe prep) |
| Confirmation required | No | Yes (since 0.3.12) |
| Restarts engine after | No | Yes |

**Rule of thumb:** use **`wipe --confirm`** when you want a clean unmanage + delete all repo-related Scubiee data. Use **`remove`** when you only want to drop registry tracking (rare).

---

## Dashboard: Forget

The operator dashboard (`scubiee dashboard`) has a **Forget** button per repo.

- Removes the project from Scubiee’s registry and deletes the index **store**
- Requires typing the exact **project id** (`ce_…`) to confirm
- Automated forget may require the repo to be **missing/offline** for a retention period (24h default) unless using operator mode
- Does **not** replace a full **`wipe`** for cleaning VectorDB, `.scubiee`, and repo tool files

For a complete cleanup of one checkout, prefer **`scubiee wipe . --confirm`** from the CLI.

---

## Multiple checkouts of the same project

If the same `project_id` is registered at more than one path (e.g. two clones):

- `wipe` / `remove` on one path removes **that checkout** from the registry
- The index store under `~/.scubiee/projects/<id>/` is deleted only when **no sibling checkouts** remain

---

## Never index a path

```bash
scubiee never-index /path/to/folder --reason "vendor mirror"
```

Persistently refuses indexing for that path. Use when a folder must never be enrolled.

---

## Wipe everything on the machine

Only when you intend to remove **all** Scubiee state:

```bash
scubiee wipe --all --confirm
```

Optional flags:

- `--keep-models` — keep CodeRank/FastEmbed caches
- `--keep-package` — keep uv tool install
- `--package` — also uninstall the scubiee package

See [Commands reference — Settings & wipe](./commands-reference.md#settings--wipe) and [Uninstall guides](./uninstall-windows.md).

---

## Related

- [Commands reference](./commands-reference.md)
- [Daily use](./daily-use.md)
- [Indexing & projects](./indexing-and-projects.md)
- [Dashboard & engine](./dashboard-and-engine.md)
- [FAQ](./faq.md)
