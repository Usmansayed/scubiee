# Session summary — Windows + Mac (through 20 Aug 2026)

Use this as memory if the chat is new. Detail of each bug: [issue-log.md](./issue-log.md). Product: [../engg/01-vision.md](../engg/01-vision.md).

## Where the code is

| Remote | URL | Role |
|--------|-----|------|
| `origin` | https://github.com/Usmansayed/new-context-engine.git | Public |
| `hidden` | https://github.com/Usmansayed/hidden-context-engine-.git | Mac/Windows handoff |

**Worktree (this machine):** `.worktrees/production-certification`  
**Branch:** `feat/production-certification`  
**Windows Python:** Miniconda 3.13 (`C:\Users\usman\Miniconda3`)

Mac agent pushed 0.2.11–0.2.13 to **hidden** first; Windows then fast-forwarded the feature branch and later pointed `main` at that tip.

## User machines

| Machine | Role | Python env |
|---------|------|------------|
| Windows | Dev, PyPI upload, this worktree | Miniconda |
| **MacBook Air Apple Silicon** | Real install trial, GPU, MCP | **`~/scubiee` venv**, Python 3.12 |

Runtime data always: `~/.context-engine/` (`accel.json`, projects, daemon). **Do not confuse with the venv path.**

PyPI credentials live in parent repo `.env` (`pipy_username` / `pipy_password` — typo prefix). **Never commit `env`.**

## Version timeline (what shipped)

| Ver | What |
|-----|------|
| **0.2.5–0.2.6** | Reliability: search path vs query, no mkdir from queries, MCP health-first, `ensure_daemon`, live reindex + FAISS ids after upsert, doctor OK when only daemon unbound, `init --fast/--roots`, Mac npm venv + git pip fallback. PyPI 0.2.6 live. npm **not** published. |
| **0.2.7** | CoreML static ONNX + fixed batch 20 + GPU-only EP. **Failed on real Mac:** invalid ORT options → silent CPU fallback. |
| **0.2.8** | Strip `UseCPUAndGPU`/`CreateMLProgram`; define ONNX `shape=[batch,seq]`. Handoff doc + `~/scubiee` note. |
| **0.2.11** (Mac) | **MLX** default on Apple Silicon; daemon **publish-after-sync**; MCP **venv interpreter** (no resolve); remove **hard tool caps**. |
| **0.2.12** (Mac) | Phase **grep+glob**; Cursor rule via setup; **MLX per-thread GPU stream**. |
| **0.2.13** (Mac) | Packaged **short** Cursor rule. |
| **0.2.14** | Windows `ctx setup` pip **PIPE deadlock** (bar stuck 31%). PyPI. |
| **0.2.15** | Skip already-installed FastEmbed deps (permission error while `ctx` held ORT files). |
| **0.2.16** | Swap mutually exclusive ORT wheels; do not warm DML on CPU onnxruntime. PyPI. |
| **0.2.17** | Windows `import resource` crash on `ctx init`. RSS via psutil. PyPI. |
| **0.2.18** | Grep honors glob + `truncated`/`has_more`; glob `**` + honest truncation; phase instructions **recommend** (no native ban). Tree version; **upload PyPI if we want pip -U**. |

PyPI latest published in this arc: https://pypi.org/project/scubiee/0.2.17/  (0.2.18 is local until twine).

## What is solved (product)

- Agent locate surface is **phase** (`map` / `focus` / `grep` / `glob` / `workspace` / `status`). Cursor rule **bans native Grep/Glob/search** for discovery. MCP instructions recommend which CE tool. `map` is ranked indexed chunks, not absence.
- `grep` searches the requested glob (not Python-only). `truncated`/`has_more` when the hit cap fires. `glob` supports `**` and does not claim empty when truncated.
- Mac GPU for **production indexing** is **MLX FP16 on Metal**.
- Windows GPU path **DirectML** verified on this PC (RX 6500M, `ctx setup` + `ctx init` Ready).
- After `ctx sync`, running daemon **reloads** search (generation bump).
- MCP on Mac **imports `pipeline`** because json points at venv python, not Cellar.
- Duplicate map/focus does not hard-fail the agent.
- User rejected CPU-only Mac; we stopped recommending `--profile cpu` as the path.

## Mac work in this arc (must not forget)

1. Clean Mac install: Python 3.10+ required; user used 3.12 + `~/scubiee`.
2. `ctx setup` CoreML crash (dynamic shapes, E5RT, zero-element rotary).
3. 0.2.7 “Ready” while actually CPU (`Unknown option: UseCPUAndGPU`).
4. Switch strategy to **MLX** CodeRank on GPU (`packages/pipeline/mlx_mac.py`).
5. Daemon vs CLI: MLX stream + publish-after-sync.
6. Phase grep/glob so agents do not mix native Grep with MCP (later: recommend, not ban).
7. `ctx setup --repair` copies rule from `packages/pipeline/templates/context-agent.mdc`.
8. Windows: pip drain, ORT DML wheel swap, `resource` crash, DML `ctx init` Ready.

Primary Mac write-up (kept): `docs/handoff-2026-08-19-mac-mcp-fixes.md`. Older CoreML story: `docs/mac-gpu-install-handoff.md`.

## Remaining / look into next

**Do not treat as done:**

1. **npm `scubiee`** — never published (404). Needs `NPM_TOKEN`.
2. **`status.sync_status` can show `needs_full`** after catchup chunked live reindex while locate still works — operator confusion.
3. **Leftover `~/.context-engine/projects/`** from path-pollution era — one-time cleanup.
4. **Large dump / folder replace** still does not auto full-index (by design: ≥50% change → full, incremental cap, `CTX_ALLOW_BG_FULL` off). Need operator message + `ctx index --force`.
5. **Foreign tree dump** at repo root (nested project source) can get embedded — allowlist / nested `.git` detector (`docs/reindexing/future-work.md`).
6. **`pip uninstall` leaves daemon** on :8765 — stop engine in uninstall hook.
7. **`feat/live-reindexing`** not merged into this line unless someone does it separately.
8. **GitHub `PYPI_API_TOKEN`** — CI publish optional; last uploads were manual twine from `.env`.
9. **CoreML path** still in tree; Mac default is MLX. Do not revive CoreML as default without a real-device pass that shows **no** CPU fallback in logs.
10. README still mentions git install `@v0.2.6` in one fallback snippet — should say latest when docs are next touched.
11. Bench junk: `docs/bench-*.err.log`, `:memory:.ses` — do not commit secrets or leftover logs.
12. **Publish 0.2.18** if users `pip install -U scubiee` should get grep/glob honesty + recommend instructions.
13. `status.sync_status` can still say `syncing` while keeper `sync_status=ready` — operator confusion (same family as item 2).

## New-session prompt (paste)

```
Read docs/session-info/README.md, session-summary.md, issue-log.md, then docs/engg/.
Branch feat/production-certification. PyPI scubiee 0.2.17 (tree may be 0.2.18).
Mac venv is ~/scubiee. GPU path is MLX FP16. Windows GPU is DirectML.
Do not Path.resolve MCP python on Darwin.
Do not hard-cap map/focus. Do not skip /v1/publish after sync.
Phase MCP instructions recommend; agent decides. map miss ≠ absence.
```
