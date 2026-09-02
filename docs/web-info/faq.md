# FAQ

Short answers to common questions. Docs assume **[scubiee 0.3.14](https://pypi.org/project/scubiee/0.3.14/)** (published on PyPI).

Full install/debug playbook: [Install & debug](./install-and-debug.md).

**Upgrading from 0.2.x?** [What's changed since 0.2.88](../whats-changed-since-0.2.88.md)

---

## General

**What is Scubiee?**  
A local code context engine: indexes your repo, embeds with CodeRank (GPU when available), and exposes search/map/focus via MCP to AI coding tools.

**What is the MCP server name?**  
**`scubiee`** (in `mcp.json`). Data lives under `~/.scubiee` and `<repo>/.scubiee`.

**Do I need to clone the GitHub repo?**  
No. Install from PyPI: `uv tool install scubiee==0.3.14` ([project page](https://pypi.org/project/scubiee/0.3.14/)).

**What Python version?**  
3.10 or newer.

**Correct first-time order?**  
`setup --repair` → `init` in the repo → `connect` for your IDE → reload MCP.

**Does `init` connect Cursor?**  
No. **`connect`** writes MCP + rules. **`init`** only enrolls/indexes the repo.

---

## Install

**uv or pip?**  
Prefer **uv tool install** — isolated CLI, clearer upgrades on Windows.

**Why `setup --repair`?**  
Safest after fresh install, upgrade, or broken reinstall. Installs missing FastEmbed/ORT extras and refreshes `accel.json`.

**Where is the embedding model?**  
Downloaded during setup (~270 MB FP16 CodeRank). Cached under FastEmbed cache dirs.

**Share diagnose with support?**  
`scubiee diagnose --no-tests --desktop` → send `Desktop/scubiee-diagnose.json`.

---

## GPU / CPU / Mac

**Windows laptop with only Intel UHD / AMD APU graphics?**  
Current builds use **`cpu`** (not DirectML). Discrete AMD/NVIDIA → **`dml`**.

**Force CPU?**  
`scubiee setup --profile cpu --repair`

**Apple Silicon?**  
Default **`mlx`** (Metal). Should not stay on CPU after `--repair`. See [Mac & Linux](./mac-and-linux.md).

---

## Usage

**Why won't init run from my home folder?**  
Safety — don’t index all of `C:\Users\you` or `$HOME`. `cd` into the project.

**What does `--fast` do?**  
Indexes `.py` under common code directories (`packages`, `src`, …) or your `--roots` list.

**What does `--confirm` do?**  
Required when more than 400 indexable files would be touched.

**How do I search from terminal?**  
`scubiee search "query" .`

**How do I update after git pull?**  
`scubiee sync .`

**Pause / resume?**  
- **Per-repo:** `scubiee pause .` → continue with **`scubiee activate .`** (since 0.3.11).  
- **Global:** `scubiee stop` → continue with **`scubiee resume`** (not `engine start`). There is no `wake`.

**Wipe one repo without a prompt?**  
`scubiee wipe . --confirm` (since 0.3.12). Without confirm, exit code **2**. See [Repository lifecycle](./repo-lifecycle.md).

**How do I unmanage a repo and delete its Scubiee data?**  
`scubiee wipe . --confirm` — removes enrollment, index, VectorDB, `.scubiee`, and repo MCP/rules. Your source code is **not** deleted. Not the same as `pause` or `stop`. Details: [Repository lifecycle](./repo-lifecycle.md).

**`remove` vs `wipe`?**  
`remove` drops registry tracking (optional `--delete-store`). **`wipe --confirm`** is the full per-repo cleanup.

**What does each MCP tool do?**  
[MCP tools reference](./mcp-tools-reference.md) — `gate`, `map`, `focus`, `grep`, `glob`, `workspace`, etc.

**`status` on a folder I never initialized?**  
`enrolled: false`, `state: "unmanaged"` — run `scubiee init .` to enroll.

**Upgrading from 0.2.88?**  
See [What's changed since 0.2.88](../whats-changed-since-0.2.88.md) — pin `scubiee==0.3.14`, run `setup --repair`, re-run `connect`.

---

## Cursor / MCP

**How do I connect Cursor?**  
After setup + init: `scubiee connect --cursor` **from the project**, then reload MCP. That writes project `.cursor/mcp.json` with an absolute pin (Cursor does not expand `${workspaceFolder}` in global MCP).

**Kiro / Copilot / Cline / Roo don’t see the repo?**  
Run `scubiee connect --<tool>` **inside that project** (workspace-local MCP).

**`status` shows `warming`?**  
Daemon starting. Retry the tool once after a few seconds; don’t poll `status()` every turn.

**Agent still uses native Grep?**  
MCP green? Re-run `connect` to refresh rules. After mid-session `init`, call `status()` once again.

**Does MCP work offline?**  
Yes after setup. HuggingFace is only needed once for the model download.

---

## Windows

**Access denied on upgrade/reinstall?**  
`scubiee unlock-tool` → reinstall → `setup --repair`. **Not** Admin/reboot. See [Install & debug](./install-and-debug.md) / [Windows](./windows.md).

**`No module named 'pipeline'`?**  
Half-deleted uv tool env — unlock or `scripts/uninstall-uv-scubiee.ps1` / `repair-uv-scubiee.ps1`, then reinstall.

**AMD discrete GPU?**  
Yes via DirectML (`dml`). Verify with `scubiee setup --status`.

---

## Data & privacy

**Does my code leave the machine?**  
No — indexing and search are local. Only the embedding model downloads during setup.

**How do I delete everything?**  
`scubiee unlock-tool` (if locked) → `scubiee wipe --all --confirm --package`. Check JSON `audit.remaining`.

---

## Errors

**`machine_not_setup`** → `scubiee setup --repair`  
**`not_configured` / missing fastembed** → `setup --repair`  
**Stale accel after reinstall** → `setup --repair` before `init`  
**Access denied (Windows)** → `scubiee unlock-tool` then reinstall  
**`project_id_mismatch`** → remove stale home registration (`scubiee remove … --delete-store`)  
**`never_index`** → path was blocked with `scubiee never-index`

---

## More detail

- [Install & debug](./install-and-debug.md)
- [Getting started](./getting-started.md)
- [Troubleshooting](./troubleshooting.md)
- [Commands reference](./commands-reference.md)
- [Cursor & MCP](./cursor-mcp.md)
