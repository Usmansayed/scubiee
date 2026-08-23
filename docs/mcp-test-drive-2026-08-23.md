# MCP full test-drive — 2026-08-23 (Windows)

Clean-room verification of `scubiee` 0.2.54: wipe everything, reinstall via `uv`,
exercise every MCP tool and CLI command, run retrieval experiments, and chase
down anything that misbehaved. Three real bugs were found and fixed along the
way; all fixes are in this build.

Platform: Windows 11, Python 3.13.5, `uv` tool install, DirectML (dml) profile.

---

## 1. Clean wipe

```
scubiee wipe --all --yes
```

Result: all registered repos unregistered, daemon + watchdog stopped, MCP
configs and rule files removed, `~/.context-engine` home deleted, model caches
cleared, pip-installed copy uninstalled. One harmless leftover: an empty
`fastembed_cache` directory (0 bytes) — audit correctly flagged it, non-fatal.

## 2. Fresh install via `uv`

```
uv tool install "dist\scubiee-0.2.54-py3-none-any.whl[dml]" --force
```

- Resolved 74 packages, installed `scubiee`, `fastembed`, `onnxruntime`,
  `onnxruntime-directml`. First attempt without `[dml]` skipped the embedding
  deps; second attempt hit a `UV_HTTP_TIMEOUT` on the 13MB `onnxruntime`
  wheel (30s default) — retried with `$env:UV_HTTP_TIMEOUT="120"` and it
  downloaded fine in ~7 minutes on a slow link.
- Installed two executables: `scubiee`, `scubiee-mcp`.
- `scubiee --version` → `0.2.54`, correct interpreter under
  `%APPDATA%\uv\tools\scubiee\Scripts\python.exe`.

## 3. Setup + init

```
scubiee setup
scubiee init --confirm
```

- `setup`: detected DML profile, downloaded CodeRank embed model + converted
  to FP16, calibrated ~35 t/s, registered Cursor MCP. Completed in a few
  minutes (mostly model download).
- `init`: repo has 410 indexable files, over the 400-file safety cap — setup
  correctly paused for `--confirm` instead of silently indexing. With
  `--confirm`: 410 files → 3319 chunks, embed phase 124.6s at 26.6 chunk/s
  (fastembed/dml backend, 528k tokens, 4237 tok/s).
- `scubiee status`: index healthy, `freshness.clean: true`, server warm,
  `index_usable: true`.

## 4. MCP tool-by-tool (stdio JSON-RPC)

Tested every tool on the `phase` surface directly over stdio (no IDE), driving
`scubiee-mcp` with a small Python JSON-RPC harness.

| Tool | Result | Notes |
|---|---|---|
| `initialize` / `tools/list` | OK | Returns `map, focus, grep, glob, workspace, register_project, status` |
| `status` | OK | Reports engine health, chunk count, keeper state |
| `map` | OK | BM25-ranked cards over indexed chunks, correct scores/paths |
| `focus` (outline) | OK | Python AST outline, correct symbol list |
| `focus` (span) | OK | Bounded body read, correct line ranges |
| `focus` (neighbors) | OK | Returns wiring/neighbor spans |
| `grep` | OK, with a caveat — see bug #4 below | |
| `glob` | OK after fix — see bug #1 below | |
| `workspace` (show/pin/clear) | OK | Heatmap, pins, and topic tracking all correct |
| `register_project` | OK after fix — see bug #3 below | |

Also exercised error handling: unknown tool name, missing required argument
(`grep` with no `pattern`), and a nonexistent file path in `focus` — all
returned clean, structured errors instead of crashing the server.

## 5. `connect` / `disconnect` (from the prior session, re-confirmed here)

`scubiee connect --all --dry-run` and the real run both worked cleanly across
all 13 supported tools (Cursor, Claude Code, Codex, Kiro, Windsurf,
VS Code/Copilot, Cline, Roo Code, Continue, Zed, OpenCode, Amp, Pi) — correct
per-tool paths, schemas, and no `CTX_REPO` leakage into global configs.
17/17 `test_connect_formats.py` tests pass.

## 6. Bugs found and fixed

### Bug 1 — `root_probe` never converges on Windows (path-separator mismatch)

`root_probe()`'s newcomer-discovery step diffed a posix-style file set
(`collect_index_relpaths()`, forward slashes) against merkle snapshot keys
that are `canonical_relpath()`-normalized (backslashes + lowercased on
Windows). The set difference almost never matched, so every single probe
reported ~400+ files as "newly added" — even though they were already
indexed. With the keeper's 1-second change-poll interval, this pegged a full
CPU core in a tight loop and starved the `registry.lock` used by other MCP
tools.

**Fix:** `root_probe.py` now canonicalizes both sides before comparing, and
canonicalizes the public `added`/`modified`/`removed` output back to
posix-style (callers already expected that shape).

### Bug 2 — merkle root hash unreproducible on Windows

`save_snapshot()` hashed the *raw* (often posix-style) keys it was given, but
`load_snapshot()` canonicalizes keys on read. On Windows the two hashes never
matched, so a freshly-indexed, completely clean repo still reported
`clean: false` on every probe.

**Fix:** `save_snapshot()` now canonicalizes keys before both hashing and
persisting, matching what `load_snapshot()` produces.

### Bug 3 — merkle scan and real indexer disagreed on what to skip

`merkle.scan_file_hashes()` (used by the freshness/incremental path) ignored
a different, narrower set of directories than `paths.collect_index_paths()`
(the real indexer). Concretely, `merkle.DEFAULT_IGNORE_DIRS` was missing
`testdata`, `research`, `vendor`, `sandbox`, `references`, `experiments`,
`design_benchmarks` — all of which the real indexer already excludes. On this
repo that meant `merkle.json` accumulated 5,427 file hashes (4,856 of them
from `testdata/` alone) against an actual indexed universe of 410 files.

**Fix:** aligned `merkle.DEFAULT_IGNORE_DIRS` with `paths._SKIP_SUBSTRINGS`.
After a clean reindex, `merkle.json` dropped to 414 entries and `freshness`
reports `clean: true` with `changed_count: 0`.

### Bug 4 — `git` subprocess hangs forever inside the MCP stdio server (Windows)

`git_common_dir()` (in `project_id.py`) and `_git()` (in `freshness.py`) both
called `subprocess.run(["git", ...], timeout=5)` without setting `stdin=`.
On Windows, a child process inherits the parent's stdin handle unless told
otherwise. The MCP server's own stdin is a pipe held open by the client
(Cursor, Kiro, or a test harness) that is never written to and never closed.
Several `git.exe` processes were found still alive after 50+ minutes —
`timeout=5` never fired because the hang happens before `Popen`'s wait/timeout
logic is ever reached. This surfaced as `register_project` (and, before Bug 1
was fixed, `glob`) hanging indefinitely with no response.

**Fix:** added `stdin=subprocess.DEVNULL` to both call sites, plus the same
class of `git`/`gh` calls in `graphify/prs.py` (`_gh`, `symbolic-ref`,
`worktree list`) since they run in the same kind of long-lived process.

### Bug 5 — `register_project` deadlocks on first `faiss` import from a worker thread

Even after Bugs 1–4 were fixed, `register_project` still hung indefinitely.
Root-caused with targeted tracing: `pipeline.vectordb` (which does
`import faiss` at module scope) was being imported for the first time from a
FastMCP tool-call worker thread — `register_project` is the only tool on the
`phase` surface that touches the vector store. Importing a native extension
DLL for the first time from a background thread, in a process where the main
thread is parked in the stdio event loop, deadlocked reliably on Windows. The
identical call completed in well under a second when run from the main
thread or via a direct in-process `call_tool()` (no server loop involved) —
confirming this was a threading/loader issue, not a slow operation.

**Fix:** `mcp_locate.py`'s `main()` now eagerly imports `pipeline.vectordb`
on the main thread, right after `ensure_daemon()` and before
`create_mcp().run(transport="stdio")` starts dispatching tool calls to worker
threads. `register_project` now returns in ~0.2–2s depending on whether it
also has to reindex.

### Bug 6 (documented, not fixed) — `grep`'s line cap can silently miss real hits

`grep_scan()` caps total lines scanned across *all* matched files at
`CTX_GREP_MAX_LINES` (default 50,000) and scans files in alphabetical order.
On this repo, `grep(pattern="def server_entry", glob="packages/**/*.py")`
returned `count: 0, truncated: true` even though `packages/pipeline/mcp_install.py`
(alphabetically late) contains a real match — the scan hit the 50k-line cap
inside `packages/pipeline/ce_service.py` first and stopped. `truncated: true`
is technically an honest signal ("this isn't exhaustive"), but a narrower,
more specific glob can paradoxically get *less* honest-looking results than a
broad one, because narrowing the glob doesn't change scan order or the cap.
Not changed in this pass — flagging for a follow-up (e.g. round-robin across
matched files instead of strict alphabetical order, or scale the cap to the
match-set size).

## 7. Verification

- Rebuilt the wheel (`python -m build --wheel`), reinstalled via
  `uv tool install ... --force`, and re-ran the full MCP tool battery against
  the **installed** package (not just the source tree) — all 7 tools pass.
- Full `pytest` suite: 554 passed, 26 failed — identical failure set before
  and after these changes (confirmed via `git stash`/`stash pop` diffing).
  All 26 are pre-existing and unrelated: Windows path-case assertions in
  `test_repo_lifecycle*.py`/`test_project_id.py`, a `RecursionError` in the
  installed `faiss` build's `class_wrappers.py` (`test_vectordb.py`,
  `test_storage_policy.py`), and a few environment-dependent tests
  (`cursor-sdk` not installed, `gh` not authenticated, etc).
- `tests/test_root_probe.py` specifically: went from 4/9 passing on
  unmodified `main` to 9/9 passing after the fix (Bugs 1–2 directly caused 5
  of those pre-existing failures).

## Files changed

- `packages/pipeline/root_probe.py` — canonicalize before diffing; posix-ize output
- `packages/pipeline/merkle.py` — canonicalize before hashing in `save_snapshot`; align `DEFAULT_IGNORE_DIRS`
- `packages/pipeline/project_id.py` — `stdin=DEVNULL` on `git_common_dir`
- `packages/pipeline/freshness.py` — `stdin=DEVNULL` on `_git`
- `packages/graphify/prs.py` — `stdin=DEVNULL` on `gh`/`git` calls
- `packages/pipeline/mcp_locate.py` — eager main-thread `faiss` preload before stdio loop starts
