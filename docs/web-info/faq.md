# FAQ

Short answers to common questions.

---

## General

**What is Scubiee?**  
A local code context engine for Cursor: indexes your repo, embeds with CodeRank (GPU when available), and exposes search/locate via MCP.

**Do I need to clone the GitHub repo?**  
No. Install from PyPI: `uv tool install scubiee`.

**What Python version?**  
3.10 or newer.

**Latest version?**  
Check PyPI: [scubiee](https://pypi.org/project/scubiee/). Docs assume **0.2.50**.

---

## Install

**uv or pip?**  
Prefer **uv tool install** — isolated CLI, easier upgrades on Windows.

**Why `setup --repair` instead of `setup`?**  
On Windows, `--repair` is safer after fresh install or upgrade; it avoids ordering bugs with FastEmbed and reuses valid GPU caches.

**Where is the embedding model stored?**  
Downloaded during setup (~270 MB FP16 CodeRank). Cached under FastEmbed cache dirs (`%TEMP%\fastembed_cache` on Windows, `~/.cache/fastembed` on Unix).

---

## Usage

**Why won't init run from my home folder?**  
Safety — indexing `C:\Users\you` or `$HOME` would pull in personal files. `cd` into your project first.

**What does `--fast` do?**  
Indexes only `.py` files under common code directories (`packages`, `src`, …) or your `--roots` list.

**What does `--confirm` do?**  
Required when more than 400 indexable files would be touched (configurable via `CTX_INCREMENTAL_MAX_TOUCH`).

**How do I search from terminal?**  
`scubiee search "query" . --local`

**How do I update after git pull?**  
`scubiee sync .`

---

## Cursor / MCP

**MCP not showing tools?**  
Run `scubiee setup --repair`, then reload MCP in Cursor Settings.

**Agent still uses native Grep?**  
Check project Cursor rules; CE MCP should be primary when healthy.

**Does MCP work offline?**  
Yes — everything is local. HuggingFace is only needed once for model download during setup.

---

## Windows

**Why Access denied on uninstall?**  
Cursor MCP locks the uv tool Python. Run `scubiee stop`, wipe, quit Cursor. See [Uninstall on Windows](./uninstall-windows.md).

**AMD GPU support?**  
Yes via DirectML (`dml` profile). Verify with `scubiee setup --status`.

**faiss import error?**  
Incomplete wheel extract — run repair script or see [Windows guide](./windows.md).

---

## Mac

**Apple Silicon GPU?**  
Uses MLX Metal by default — see [Mac & Linux](./mac-and-linux.md).

---

## Data & privacy

**Does my code leave the machine?**  
No — indexing and search are local. Only the embedding model downloads from HuggingFace during setup.

**How do I delete everything?**  
`scubiee wipe --all --yes --package` (after `scubiee stop`).

---

## Errors

**project_id_mismatch**  
Often stale registration of your home directory. `scubiee remove ~ --delete-store` and delete `~/.context-engine/id.json` in home if present.

**never_index**  
Path was blocked with `scubiee never-index`.

**Preflight missing fastembed**  
`scubiee setup --repair`

---

## More detail

- [Troubleshooting](./troubleshooting.md)
- [Commands reference](./commands-reference.md)
- [Indexing & projects](./indexing-and-projects.md)
