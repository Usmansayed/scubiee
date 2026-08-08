# SDK Dev-Trial Runbook (Context Engine vs Graphify)

How the Cursor SDK development trial works, how we rank the arms, the preflight
gate, and every failure we already paid to learn — so we never repeat them.

Scripts:
- `scripts/experiments/sdk_mcp_dev_trial.py` — the harness (arms, observe_run,
  evaluate, report).
- `scripts/experiments/sdk_mcp_smoke.py` — MCP config, rule staging,
  `ensure_engine_repo`, message normalization.
- `scripts/experiments/_run_trial_unfix.py` — driver: runs `--preflight`, cleans
  stale engines, verifies the live MCP `search` tool, runs the paid trial.
  (Name is historical — it no longer "un-fixes" anything; the task is a clean
  feature build.)

---

## 0. TL;DR — always do this order

1. **Preflight first (free, no API):** run the entire non-agent path for both
   arms. Never launch a paid run until this is green **twice**.
   ```
   python scripts/experiments/_run_trial_unfix.py --preflight --arms context_engine,graphify
   ```
2. Only if preflight is green, run the paid trial:
   ```
   python scripts/experiments/_run_trial_unfix.py --arms context_engine,graphify --timeout 900
   ```
3. Rank arms by **`work_complete`** + **`total_tokens`** (see §4). Not by
   `status`.

Golden rule: **if it can be tested for free, test it for free before spending.**
Every failure below was discovered by burning a paid agent run when a preflight
would have caught it for $0.

---

## 1. SDK completion detection (the expensive lesson)

The local bridge **keeps the run's message stream open after the agent
finishes**, and the run's `status` never flips to a terminal value on the
stream. So you cannot detect completion by:
- waiting for `run.messages()` to end (it doesn't), or
- watching `run.status` in the stream (stays `running`), or
- calling `run.wait()` (it drains the stream, which never closes → hangs).

### What actually works
- `client.get_run(run_id)` → cheap **status snapshot** (unary RPC, returns
  immediately). Poll it for a terminal status.
- `client.wait_live_run(run_id)` → authoritative `RunResult` (status + usage),
  BUT it **blocks server-side while the run is in progress** and a long run
  **exceeds the bridge read timeout (~120s) → `APITimeoutError: ReadTimeout`**.

### The pattern we ship (`observe_run`)
1. Drain `run.messages()` in a task purely for tool/text observation (the send
   stream must be consumed for the run to make progress).
2. A waiter task **polls `get_run`** every `TERMINAL_POLL_S` (6s). Once status is
   terminal, it calls `wait_live_run` **once** (returns instantly now, no
   ReadTimeout) to get authoritative usage.
3. Whichever fires first ends observation. The waiter is checked **before** any
   idle/ceiling logic, so a run that does finalize is never cancelled.

Terminal statuses: `{"finished","error","cancelled","expired"}`.

### Failure signatures → cause
| Symptom in `*-arm.json` | Cause | Fix |
|---|---|---|
| `error: wait_live_run failed: APITimeoutError: ReadTimeout`, `status=timeout`, `usage=None` | Called `wait_live_run` on a long in-progress run; blew past the ~120s bridge read timeout | Poll `get_run` for status; only call `wait_live_run` after terminal |
| `status=cancelled`, `status_history=['running','cancelled']`, `error: run idle for 185s` | Old harness watched the stream for a terminal status that never comes, then idle-cancelled | Use the `get_run`/`wait_live_run` waiter |
| `conversation capture failed: TimeoutError` | `run.conversation_json()` unary is slow/wedged on a busy run | Non-fatal; MCP attribution already comes from stream events. Bounded by `CONVERSATION_GRACE_S` |

---

## 2. Local runs don't self-finalize → idle-finalize

Even with the waiter, local runs frequently **never report terminal**: the agent
completes its turn, goes silent, but neither the stream nor `get_run` flips
terminal. So after the agent stops it would ride to the full ceiling.

Mitigation: a **stream-idle window** (`IDLE_TIMEOUT_S = 120s`) is treated as
"agent done" and finalizes the arm (cancels + captures usage). Kept generous so
a slow, silent tool call isn't mistaken for completion.

Consequence: **`status` is usually `cancelled` even for successful arms.** This
is expected and benign. Rank by `work_complete`, never by `status` (see §4).

Constants (`sdk_mcp_dev_trial.py` top):
- `IDLE_TIMEOUT_S = 120` — idle-finalize window.
- `TERMINAL_POLL_S = 6` — `get_run` poll interval.
- `WAIT_GRACE_S = 60` — bound on the final `wait_live_run`/`run.wait`.
- `CANCEL_DRAIN_GRACE_S = 60` — stream drain grace after a cancel.
- `CONVERSATION_GRACE_S = 45` — bound on conversation capture.
- Per-arm ceiling via `--timeout` (default 900s). Idle-finalize ends healthy
  arms ~120s after the agent stops, well under the ceiling.

---

## 3. The stale-daemon race (why `run_post_tests` blew up)

Error: `RuntimeError: engine serves '<OLD workspace>', expected '<current>'`.

Root cause: the Context Engine engine is a **singleton on port 8765**. Leftover
processes from previous/killed runs squat and re-point it:
- `pipeline engine run <old_ws> --port 8765` (+ its `engine watchdog`) survive a
  killed run.
- Orphaned `pipeline.mcp_locate` from dead runs have `CTX_REPO=<old_ws>` and
  their **background sync re-points the shared engine** at the dead workspace.

`ensure_engine_repo` does `stop_daemon` + `start_daemon`, but it cannot evict a
squatter it doesn't track, so it raises on the re-check.

### Fix (auto, at trial/preflight start)
`_run_trial_unfix.py :: kill_stale_trial_engines()`:
- Kills python procs whose command line matches `pipeline (engine|.mcp_locate)`
  **and** references `ce_dev_trial` (trial workspaces only — Cursor's own
  main-repo MCP is left untouched).
- Calls `pipeline.daemon.stop_daemon()` so `ensure_engine_repo` starts clean.

Do NOT blanket-kill `python` or all `pipeline.mcp_locate` — you'll take down
Cursor's chat MCP and `navigation.mcp`.

Manual inspection when debugging:
```
Get-NetTCPConnection -LocalPort 8765 | ? State -eq Listen
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  select ProcessId,@{n='Cmd';e={$_.CommandLine}} | fl
```
The engine's served repo: `python -c "from pipeline.client import EngineClient; print(EngineClient().status()['repo'])"`.

---

## 3b. The empty-index confound (the silent tie-maker)

**Symptom:** the Context Engine arm "works" but makes many grep calls and its MCP
results are thin — the two arms come out a near-tie. `status()` for the workspace
shows `warm_state: error`, `warm_error: "No index found"`; a live `search`/`map`
returns `0` hits; `pipeline index` prints `graphify-files:0`, `chunks: 0`.

**Root cause:** `graphify.extract.collect_files()` returns `[]` when **any path
component of the scanned root is a noise dir** (`_SKIP_DIRS`: `out`, `dist`,
`build`, `target`, `.venv`, ...). The old trial output lived at
`ROOT/out/experiments/sdk_mcp_dev_trial/<ts>/<arm>_workspace` — the `out`
component alone makes `collect_files` skip the **entire** workspace. So the CE
index is built over **zero files**, `map`/`focus`/`search` return nothing, and
the agent silently falls back to grep. The arm was never actually exercising
semantic retrieval — every prior "tie" was measuring grep-vs-graph, not
search-vs-graph.

**Fix:** `_default_output()` now places workspaces in the **system temp dir**
(`<tempdir>/ce_dev_trial/<ts>`), which has no noise component, so the index is
actually built. Temp also keeps the source repo's git status clean.

**Guard:** preflight's `verify_mcp_search` does a live `search(k=5)` and **aborts**
unless it returns non-empty results (polling up to 180s for warm). An empty index
can never again reach a paid run undetected.

Sanity check any workspace root before trusting a run:
```
python -c "import sys; sys.path.insert(0,'packages'); from pathlib import Path; \
from graphify.extract import collect_files as c; \
print(len(c(Path(r'<ws>'), root=Path(r'<ws>'))))"   # must be > 0
```

---

## 4. How we rank the arms

`evaluate_development_arm` intentionally ignores run status for success:

- **`work_complete`** = all of:
  - expected MCP provider observed (`context-engine` / `graphify`),
  - no unexpected provider,
  - usage present,
  - implementation present in diff (`packages/pipeline/mcp_locate.py` **and**
    `tests/test_mcp_locate.py`),
  - focused tests passed.
- **`quality_pass`** = `work_complete and status == "finished"`. Local runs rarely
  emit `finished`, so **treat `quality_pass` as advisory only**; use
  `work_complete`.

**Token ranking:** compare `usage.total_tokens` per arm (authoritative:
`usage_source in {run_result, run_property}`; `none` means capture failed → the
run is invalid, do not rank it).

**Statistical honesty:** a single run per arm is not a result. Agent tool
behavior is high-variance (observed `grep` 0 in one run, 32 in another for the
same arm). For any real claim, run **N ≥ 5 per arm** and compare token
distributions, not single points.

Extract:
```
python scripts/experiments/_compare_tokens.py   # point it at the run dir
```

---

## 5. The task (a vague, discovery-bound feature)

The trial task is a **human-style, vague** feature request (`SHARED_PROMPT`): the
user complains that code search is dumb about terse/abbreviated queries
("auth cfg", "db conn", "getUserConfig") and asks for **query expansion** — a way
to turn it off, tests, and a short doc. Crucially it names **no files and no
private symbols**. The agent has to *discover* where a query is tokenised before
retrieval and wire the feature in there — which is exactly the work the MCP is
meant to accelerate. Spoon-feeding paths (the previous version) removed all
discovery and let an arm win while ignoring its MCP entirely.

Each arm starts from an **identical clean copy** (no `copy_workspace`
monkeypatch), so the diff reflects a genuine multi-area dev session.

### Scoring the feature (path-agnostic)
Because the prompt is vague, scoring judges the **shape** of a real change, not
exact paths:
- `implementation_present` = the diff touches **≥2 non-test source files** under
  `packages/` **and** adds a new `tests/test_*.py`. (`changed_files(diff)` +
  `added_test_files(diff)`.) `source_files_changed` and `docs_touched` are
  reported for context.
- `work_complete` additionally requires the arm to **actually use its MCP at
  least once** (`expected_provider in providers`), a captured usage record, and
  passing tests — an arm that ignores its tool cannot pass.
- `run_post_tests` runs the agent's new tests **plus** the regression module
  (`tests/test_mcp_locate.py`, minus the flaky live flow); all must pass.
- Baseline is green on the clean copy; the agent's own new tests must pass
  post-run.

---

## 6. Preflight — the free gate (run this, always)

`_run_trial_unfix.py :: preflight()` runs, per arm, with **no `agent.send`**:
`kill stale engines → copy + un-fix → baseline hash parity → index → (CE)
ensure_engine_repo → (CE) verify_mcp_search → baseline pytest → git diff →
evaluate`. Prints `PASS`/`FAIL`.

`verify_mcp_search(ws)` (CE arm only) proves the tool surface is actually updated
before spending: it loads the **source** `create_mcp()`, asserts `search` is in
the registered tools, asserts the **workspace copy** of `mcp_locate.py` also
contains the `search` tool (`name="search"`), then does a **live** `search(query,
k=5)` against the freshly-pointed engine and requires non-empty `results`. A
stale/broken MCP fails here for $0 instead of mid-run.

This exercises the exact daemon + `run_post_tests` path that kept failing. If it
passes twice, the paid run's setup is proven. Cost: $0, ~40–70s.

```
python scripts/experiments/_run_trial_unfix.py --preflight --arms context_engine,graphify
```

---

## 7. Fairness (both arms)

Rules are staged per arm (`stage_retrieval_rule`) and delivered via
`setting_sources=["project"]` + `alwaysApply: true`. Both rules **encourage the
MCP as the first move for discovery** and are symmetric, each with an explicit
**"when to use which tool"** section so the agent knows what to reach for:
- CE (3 tools): reach for `search(query, k, fetch)` FIRST on new/vague queries;
  `read(target, neighbors, max_chars)` to open a specific span before editing
  (session-deduped; `neighbors=true` adds 1-hop callers/callees instead of a grep
  sweep); `status` for health. Grep is a fallback *after* search comes up empty.
- Graphify: reach for `query_graph` FIRST on new/vague queries; `get_node` for a
  known symbol; `get_neighbors`/`shortest_path` for callers/relationships. Grep
  is a fallback *after* the graph comes up empty.

Neither rule bans Grep, but both explicitly say **don't lead with a blind grep to
locate unfamiliar code — that's what the MCP is for**. Shell for tests/build/git
is explicitly allowed (not "discovery"). The same when-to-use guidance is
mirrored in the CE MCP `SERVER_INSTRUCTIONS` so it reaches the agent even without
the rule.

---

## 8. Known-benign noise

- Trailing `Exception ignored in: <_ProactorBasePipeTransport.__del__> ... I/O
  operation on closed pipe` on process exit — harmless Windows asyncio teardown.
- `logfire-plugin ... ImportError: cannot import name 'LogData'` on every python
  start — unrelated pydantic/otel plugin warning.
- `status=cancelled` on successful arms — see §2.

---

## 9. Regression coverage

`tests/test_sdk_mcp_dev_trial.py` (run: `pytest tests/test_sdk_mcp_dev_trial.py -q`):
- finish via authoritative signal must **not** cancel the run,
- ceiling still cancels a genuinely stuck run,
- **`get_run` polling** completes long runs without `wait_live_run` blocking,
- legacy idle/ceiling behaviour for test doubles without a `.client`.

If you change `observe_run`, these must stay green before any paid run.

`tests/test_mcp_locate.py`:
- exact tool set = `{search, read, status}`,
- `search` returns a flat `results[]` (rank/file/lines/score/why), `fetch=true`
  inlines each hit's `code`,
- `read` resolves a top hit → handle + body, and a **repeat read of the same span
  returns an `unchanged` stub with the same handle** (session dedupe),
- `read(handle=…)` re-materializes a stored span body.

---

## 10. MCP tool surface (current)

The Context Engine MCP ships **exactly three tools** — data-backed from ~200
TraceLab sessions where locate+read are ~46% of all agent tool calls and the
dominant waste is redundant/duplicate reads:

- **`search(query, k, fetch, max_chars)`** — semantic search fused from
  embeddings + BM25 + graph. `k` = how many hits (r5/r10...), `fetch=true` inlines
  code bodies. The encouraged default for soft/new queries. Kills redundant
  *locate*.
- **`read(target, path, query, handle, neighbors, max_chars)`** — open the right
  span **once**. `target=` a symbol/phrase/path, or `path=`(+`query=`) to pick the
  span, or `handle=` to re-open a prior span. `neighbors=true` attaches capped
  1-hop callers/callees (the graph) with small bodies. **Session-deduped:**
  re-reading the same span returns an `unchanged` stub (no resend). Folds the old
  `focus`/`expand`/`recall` and kills redundant *read*.
- **`status`** — engine health + session size + tool list.

Retired: `map`, `focus`, `workspace`, `recall`, `expand` — their value is folded
into `search` (cold-start) and `read` (span reuse + graph neighbors). Fewer tools
= less choice overhead and less context per call for the same coverage.

Rule tone is **encourage, not force** (`.cursor/rules/context-agent.mdc`): reach
for `search` first, `read` to open, Grep as a fallback when search is empty.
Preflight's `verify_mcp_search` now guarantees **both** `search` and `read`
(resolve + dedupe) are live before any paid run.
