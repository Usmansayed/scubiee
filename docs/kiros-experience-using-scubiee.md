# Kiro's experience using Scubiee

This is a first-person account, written by Kiro, of an end-to-end session working with the Scubiee project: publishing a release to PyPI, discussing a full uninstall, and then thoroughly exercising every tool on the Scubiee MCP server. Everything below is based on what actually happened in that session — real command output, real MCP tool responses, real timings. Nothing here is simulated or written from memory of how the tool "should" behave.

Date of session: September 14-15, 2026 (per system clock).
Repo: `c:\Users\usman\Downloads\context-engine` (the Scubiee source repo itself, self-hosting its own MCP server).

---

## 1. Publishing scubiee 0.3.89 to PyPI

The first task was: build and publish the latest Scubiee version to PyPI using `pipy_username` / `pipy_password` from the repo's `.env` file.

### What I checked before touching anything

- Read `pyproject.toml`: package name `scubiee`, version `0.3.89`, build backend `setuptools.build_meta`.
- Queried the live PyPI JSON API (`https://pypi.org/pypi/scubiee/json`) to see what was already published. Latest published release at the time was `0.3.67` (uploaded 2026-09-12). So `0.3.89` was a real, unpublished bump — no version-collision risk.
- Confirmed the local toolchain had what was needed: Python 3.13.5, `build` 1.6.1, `twine` 7.0.0 already installed.

### Build

```
Remove-Item -Recurse -Force dist   (if it existed)
python -m build
```

This produced both artifacts cleanly:
- `scubiee-0.3.89-py3-none-any.whl` (1,473,491 bytes)
- `scubiee-0.3.89.tar.gz` (1,599,902 bytes)

`python -m twine check dist/*` reported **PASSED** for both files — valid metadata, valid long description, no structural problems.

### Publish

Credentials were pulled directly out of `.env` (`pipy_username`, `pipy_password`) into `TWINE_USERNAME` / `TWINE_PASSWORD` environment variables for the twine subprocess, rather than being echoed anywhere. The username resolved to `__token__` (PyPI API-token auth), and I only printed the token's *length* (179 chars) to confirm it loaded — never the value.

```
python -m twine upload dist/scubiee-0.3.89*
```

The terminal output got truncated mid-progress-bar, so I didn't just trust "exit code 0" — I went back to the PyPI JSON API and pulled `https://pypi.org/pypi/scubiee/0.3.89/json` directly. That confirmed the upload actually landed:

- `scubiee-0.3.89-py3-none-any.whl`, uploaded `2026-09-14T18:25:28Z`, sha256 `021e6593...`
- `scubiee-0.3.89.tar.gz`, uploaded `2026-09-14T18:25:30Z`, sha256 `63fe515c...`

**Takeaway:** the publish flow was uneventful. Standard `setuptools` + `build` + `twine` packaging, no custom quirks. The only friction was PowerShell's progress-bar output getting truncated in the tool transcript, which is why I verified against the PyPI API instead of trusting the shell exit code alone. Given the instructions to verify actual outcomes rather than assume success from "no error," this extra check mattered.

---

## 2. The "wipe everything" request — and stepping back from it

Right after the publish, the user asked to "uninstall the full scubiee mcp and everything, wipe everything."

Before running anything destructive, I looked at what Scubiee itself exposes for teardown, because guessing at manual deletions felt riskier than using the tool's own lifecycle commands. Running `scubiee --help` and then `scubiee wipe --help` / `scubiee disconnect --help` showed a purpose-built command:

```
scubiee wipe --all --confirm
```

with flags:
- `--all` — wipes machine state: daemon, `~/.scubiee`, MCP config, rules, downloaded models, and the `scubiee` tool install itself
- `--confirm` / `--yes` — skips the interactive Y/N prompt
- `--keep-models` — optionally keep the ~270MB embedding model cache
- `--keep-package` — optionally leave the `scubiee` CLI installed

I did **not** run this. Given the safety guardrails around destructive, hard-to-reverse, broad-blast-radius operations, I explicitly flagged before acting:

- This is **machine-wide**, not scoped to this one repo — it clears every enrolled workspace on the machine, not just `context-engine`.
- It's **one-way** in practice: reinstalling means `pip install scubiee`, re-running `scubiee setup` (re-downloading the ~270MB model), and reconnecting every IDE tool again.
- It leaves `.env`, the repo source, and the already-published PyPI package untouched — only local install/state is affected.
- I asked whether the user also wanted in-repo config remnants removed (`.scubiee/`, and the various tool-specific dirs like `.cursor/`, `.copilot/`, `.claude/`, `.codex/`, `.amp/`, `.pi/`, `.config/`, `.agents/`, `.continue/`, `.kiro/`) since `wipe --all` handles machine state and MCP wiring but not necessarily everything sitting in-repo.

The user then clarified: they had *already* run the wipe themselves outside of this conversation, and the actual ask was different — verify Scubiee MCP was still usable, and instead of destroying anything, thoroughly exercise every tool and report on how it performs.

**Takeaway on this part of the experience:** Scubiee ships genuinely good lifecycle tooling (`wipe`, `disconnect`, `stop`, `halt`, `unlock-tool`) — there's a real, documented, scriptable path to a clean uninstall rather than users having to hunt down scattered state by hand. That's a meaningfully better experience than most local-daemon-based dev tools offer.

---

## 3. Verifying the MCP was actually callable

Before doing anything else, I ran `gate` to confirm the Scubiee MCP server was live and this repo was still managed:

```json
{"response":"1:ce_50dc7657eb8a657426a6f6679092a54a sid:kiro@conn-34b4d0 shared\nSession 'kiro@conn-34b4d0' may be shared across parallel chats on kiro (one MCP process). For isolation: pass a distinct session_id per chat/task, or set CTX_MCP_SESSION_ID in the host MCP env block."}
```

It responded immediately, confirming `managed: true` for `project_id ce_50dc7657eb8a657426a6f6679092a54a`, and proactively warned that the session could be shared across parallel chats on the same MCP process — a useful bit of self-awareness baked into the tool's own output rather than something I'd have to infer.

---

## 4. Full tool-by-tool testing

The Scubiee MCP surface exposes eight tools: `gate`, `status`, `map`, `pack_context`, `expand_context`, `collect_hot_context`, `workspace`, `expand`. I called every one of them, several more than once, across two different sessions (the daemon churned in between — more on that below), and paid attention to timing, correctness, and failure behavior.

### `gate`

Cheapest possible call — a short status line with project id and session id, meant to be called every turn per the workspace's own steering rules. Worked instantly every time it wasn't caught mid-restart.

### `status`

The deep diagnostic tool. `detail=summary` gives a compact health snapshot; `detail=full` dumps everything: engine health, keeper/sync state, lifecycle steps, session details, warm-phase timers. This was the single most useful tool for understanding *why* something else was slow or failing, because it exposes internal state like:

- `warm_state`, `warm_ready`, `warm_elapsed_ms`, `warm_deadline_ms`
- `ast_hydrated` (a separate readiness flag from general "ready")
- `engine.healthy`, `engine.warm_error`
- `keeper` (background sync daemon state: intervals, dirty paths, journal restore info)
- `lifecycle.steps` with a plain-English next action when something's wrong

At one point, `status` caught the engine going fully unreachable:

```json
"engine":{"healthy":false,"warm_error":"Scubiee unreachable at http://127.0.0.1:8765: timed out"},
"locate":{"state":"starting","reason":"engine_unreachable","repair":["scubiee engine ensure ."],"should_retry":true,"retry_after_s":3}
```

That's a genuinely good error surface — it names the exact repair command rather than just saying "broken."

### `map`

This is the workhorse of the whole system — a ranked semantic search over the repo returning file/symbol/score/snippet cards plus a `suggested_seed`/`suggested_seeds` field meant to feed directly into `pack_context`. Every `map` response self-reports its own timing breakdown, which made this whole review possible without external instrumentation:

```json
"timings":{"dense":true,"retrieve_mode":"D_channel_best","embed_ms":127.3,"retrieve_ms":298.9},"elapsed_ms":903.8
```

Another run: `embed_ms: 106.7`, `retrieve_ms: 17.3`, `elapsed_ms: 1429.3` (elapsed includes overhead beyond embed+retrieve — likely session bookkeeping).

So a good, specific, dense query (30-80+ tokens, real symbol/path vocabulary) resolves in roughly **0.9-1.8 seconds end to end**, with the embedding step (~100-130ms) and retrieval step (~17-300ms, quite variable) being the two measured phases.

I also deliberately tested a bad query — `"bug fix"`, two words, no code vocabulary — specifically to see if the tool enforces the query-quality bar that the workspace steering rules describe. It didn't hard-reject it. It still returned `ok:true` with three cards, but:

```json
"weak_match": true
```

and the scores were visibly low (2.2, 4.7, 3.0) compared to well-formed queries which score in the 9-18 range. So the tool self-flags low confidence rather than enforcing a hard minimum query length — the enforcement of "write ≥40 dense tokens" lives entirely in steering/rules documents that sit on top of the tool, not in the tool's own validation logic.

### `pack_context`

Takes a `seed_file`/`seed_symbol` (usually straight from `map`'s `suggested_seed`) and produces a tight heatmap of related spans — the intended "step 2" of the locate ladder. Things I confirmed work well:

- **`thin` detection.** When the heatmap only turns up a few cards clustered in one file/module, it flags `"thin":true` and explicitly tells you not to re-pack, but to call `expand_context` or read the seed file directly instead. This matched the documented ladder discipline exactly.
- **Budgeted body collection.** Calling with `include_bodies=1` and `max_bodies=3` against a seed that resolved 7 chained candidates correctly returned exactly 3 full bodies under `pack`, and the remaining 4 as id/score-only entries under `cold`. Nothing overflowed the budget.
- **Per-stage timing.** Responses include a `timing` object breaking down `load_repo_ms`, `poly_ms`, `merge_ms`, `cards_ms`, plus an `sla` object stating the target (`target_ms: 5000`) versus actual (`elapsed_ms: 278.4`). On a cache-warm call it returned in **0.3-0.4ms** (reusing a prior map's retrieval); on a cold multi-hop pack it took **278ms**, still nowhere near its own 5-second SLA budget.

One real bug I found: I deliberately passed a **nonexistent file path** as `seed_file` (`packages/pipeline/this_file_does_not_exist.py`) to see how it'd fail. It didn't fail — it returned `"ok":true`, ranked that fake path as **rank 1, `heat: "hot"`**, and told me to "Native-Read top heatmap loc spans." If I'd followed that instruction literally, I'd have tried to read a file that doesn't exist. It silently backfilled ranks 2-4 from a previous session's leftover map results rather than surfacing an error about the bad seed. **This is a genuine gap: `pack_context` does not validate that a seed path exists before ranking it as a hot card.**

### `expand_context`

This is where the experience got the most inconsistent, and it's the most important finding from the whole session.

In one session, I called `expand_context` on a valid seed/symbol and it returned:

```json
{"ok":false,"error":"ast_warming","status":"warming","hydrate_ms":147.0,
 "hint":"AST bundle not ready (hydrate=miss, 147.0ms). Background bake started — retry expand_context in a few seconds; map/pack stay available."}
```

I retried it exactly as instructed — waited 6s, 15s, 30s, 45s — and every single retry came back with the same `ast_warming` state, each time reporting a fresh "hydrate=miss" and "background bake started," never converging to ready across roughly 70+ seconds of real waiting. Meanwhile `map` and `pack_context` worked fine throughout, because they only depend on the semantic/dense index, not the AST bundle.

In a **later** session (after the MCP worker had restarted several times due to a mid-session version upgrade), the exact same tool against a comparable seed came back instantly:

```json
{"ok":true, ..., "elapsed_ms":1.2, "hydrate_ms":0.3, "hydrate_source":"cache"}
```

So the behavior is not "always broken" — it's **inconsistent and stateful in a way that isn't obvious from the outside**. `status` exposes an `ast_hydrated` boolean separate from the general `warm_ready`/`ready` flags, and I observed `ast_hydrated: false` even while the engine reported full `READY` runtime state. That's the crux of it: general "the engine is up" readiness and "the AST bundle is baked" readiness are two different lanes, and only one of them is visible in the headline `agent_ready: "yes"` signal. An agent (or a person) trusting `agent_ready` alone could still hit a wall on `expand_context`/`collect_hot_context` specifically.

### `collect_hot_context`

Pulls full bodies for cards already sitting in the session's accumulated heatmap, above a score `threshold` (default 0.82, I tested at 0.5). Worked correctly — returned exactly the one card that met the bar, with real source text. Small inconsistency: unlike `map`/`pack_context`, its response had no `elapsed_ms` field, so I couldn't get a clean timing read on it the way I could for the others.

While the AST bundle was stuck warming (see above), `collect_hot_context` failed the same way `expand_context` did:

```json
{"ok":false,"error":"ast_warming","status":"warming",
 "hint":"No card loc spans to read yet and AST not warm. Native-Read heatmap locs, or retry after expand hydrates."}
```

Consistent with `expand_context` sharing the same AST dependency — that's at least internally coherent, even though the underlying stall is a problem.

### `workspace`

Three actions tested: `show`, `pin`, `clear`.

- `show` returned the session's live state: topic, pins, heatmap (with per-file `hits` and `heat` scores accumulating correctly across successive `map`/`pack_context` calls), spans, focus_seen, and map query history.
- `pin` on a real repo-relative path (`packages/pipeline/mcp_lifecycle.py`) succeeded and the path showed up in `pins` on the next `show`.
- `clear` fully reset everything — pins, heatmap, spans, topic, and query history all came back empty on the following `show`. No partial-clear weirdness.

This tool did exactly what it says it does, no surprises.

### `expand`

Re-materializes a previously-served span by handle. My first attempt used the wrong id format — I passed a raw `map`-card style loc range (`packages/pipeline/mcp_locate.py:1-60`) instead of a real session handle, and got back:

```json
{"ok":false,"error":"unknown handle packages/pipeline/mcp_locate.py:1-60",
 "hint":"recall() for valid handles; search again if stale."}
```

That's the tool correctly rejecting bad input — my mistake, not a bug — but the error message doesn't explain *what a valid handle looks like*, which cost me a retry to figure out. The correct format turned out to be the `file::symbol` id shape (e.g. `packages/pipeline/mcp_lifecycle.py::engine_warming_payload`), and once I used that, it worked immediately (`elapsed_ms`-free but instantaneous in practice), returning the exact source span with `start_line`/`end_line`.

---

## 5. Daemon stability during testing

This wasn't something I went looking for — it happened organically mid-session and turned into one of the more interesting findings.

Partway through testing, a `gate` call returned:

```
[scubiee] MCP worker restarted: gen=2 version=0.3.102 build=0.3.102-1790162779 prev_exit=0. Tool schema may have changed.
1:ce_7d597c1390dca6a1c5b8c4d661f421be warming retry:3 sid:kiro@conn-7e7b60 shared
```

The daemon had auto-upgraded itself mid-session, from the `0.3.89` I'd just published up to `0.3.102` — a jump of 13 patch versions, meaning there had been a burst of releases in between that I wasn't tracking. That's Scubiee's self-update mechanism kicking in unprompted, which is a neat feature in principle (you never have to manually run `scubiee upgrade`), but it directly disrupted the test session:

- `gen=1 → gen=2 → gen=3 → gen=4`: four separate worker restarts observed across the session.
- Each restart temporarily broke everything with `engine_unreachable` and reset `warm_elapsed_ms` back near zero.
- One restart cycle took about 20-30 seconds of real wall-clock waiting before `status` reported `READY` again with a *new* session id each time (`kiro@conn-34b4d0` → `kiro@conn-104980` → `kiro@conn-7e7b60` → `kiro@conn-b281a0`).
- Every single one of these transitions was accompanied by a clear, actionable status payload (`should_retry: true`, `retry_after_s: 3`, a named repair command) — the tool never left me guessing about what was happening or what to do about it.

So the instability was real and directly observed, not inferred — but the tool's own signaling about that instability was consistently good.

---

## 6. Overall assessment

**What worked well:**
- The core locate ladder (`map` → `pack_context` → `expand_context`/`collect_hot_context`) is coherent and matches its own documented design. `thin` detection, seed suggestions, and budgeted body collection all behaved exactly as documented.
- Timing self-reporting (`elapsed_ms`, and deeper breakdowns like `embed_ms`/`retrieve_ms`/`poly_ms`) is genuinely excellent — most MCP tools give you nothing like this, and it made rigorous review possible without any external instrumentation.
- Error/warming states are consistently actionable: every failure I hit (`ast_warming`, `engine_unreachable`, `unknown handle`) came with a specific hint and, often, a named repair command.
- `workspace` session state (heatmap, pins, clear) works precisely as documented with no edge-case surprises.
- Lifecycle tooling (`wipe`, `disconnect`, `stop`, `halt`) is thorough and scriptable — a genuinely clean uninstall path exists, which is rare for local-daemon dev tools.
- When warm, response times are good: `map` ~0.9-1.8s, `pack_context` sub-millisecond on cache hits and ~280ms cold, `expand`/`expand_context` sub-millisecond once AST is actually hydrated.

**What didn't work well / real issues found:**
1. **AST hydration can stall independently of general readiness.** `status.ast_hydrated` can be `false` even when the engine reports full `READY`, and `expand_context`/`collect_hot_context` depend on that specific flag while `map`/`pack_context` don't. In one session this stall didn't resolve across 70+ seconds of retries; in another session it resolved instantly. The headline `agent_ready: "yes"` signal doesn't reflect this, so an agent trusting that one field can still hit a wall on half the tool surface.
2. **`pack_context` doesn't validate seed paths.** A nonexistent file passed as `seed_file` was accepted and ranked as the top "hot" heatmap card rather than rejected or flagged, which could send a caller to read a file that doesn't exist.
3. **Query-quality enforcement is external, not internal.** `map` will happily return `ok:true` on a two-word, low-information query — it self-flags `weak_match:true` and drops scores, but doesn't push back. The "write dense, ≥40-token queries" discipline is entirely a steering-doc convention layered on top, not something the tool itself enforces.
4. **Silent mid-session version upgrades disrupt work in progress.** The daemon self-upgraded from 0.3.89 to 0.3.102 without any explicit action from me, causing four observed restart cycles and temporary tool unavailability during active use. The recovery signaling was good, but the disruption itself was not something I asked for or was warned about ahead of time.
5. **Minor telemetry inconsistency.** `collect_hot_context` and the bad-handle `expand` error path don't include the `elapsed_ms` field that `map`/`pack_context`/successful `expand_context`/`expand` calls do, making cross-tool timing comparisons slightly incomplete.

**Bottom line:** the design of the locate ladder and its self-describing telemetry are strong, and the tool is genuinely pleasant to work with when the engine is warm and stable. The rough edges are concentrated in exactly the places you'd expect for a local daemon with a background indexing pipeline: readiness-state granularity (AST vs. semantic), input validation on seeds, and resilience across silent self-upgrades.

---

## 7. Follow-up session: trying the updated Scubiee (0.3.102 → 0.3.109)

Same repo, same self-hosted MCP server, revisited a short time later at the user's request to "try the updated Scubiee and share your experience." The daemon had auto-upgraded again in the background: last session ended around `0.3.102`; this session it reported `scubiee 0.3.109` via `scubiee --version` — 7 more patch releases shipped in between, none of them triggered by me.

### What's better

**Retrieval got smarter.** `map` cards now show `"source":"D_channel_best:bm25+dense+graph"` on several results, versus only `"D_channel_best:dense"` in the previous session. That's a hybrid BM25 + dense-embedding + graph-neighbor retrieval path that wasn't visibly active before. It showed in practice too: querying for the exact "stale while syncing" behavior I'd just seen in a `status` response surfaced `derive_agent_ready` as the #1 card, and — notably — also surfaced the actual **unit test** for that exact state (`tests/test_mcp_exploration_regressions.py::test_derive_agent_ready_stale_while_syncing`) unprompted. That's a real, concrete quality improvement: the graph/hybrid signal found not just the implementation but the test proving the behavior is intentional, in the same call.

**A new, more honest readiness state.** `status` now exposes `agent_ready: "stale"` (previously I'd only seen `"yes"`, `"no"`, and `"warming"`), paired with `agent_ready_note: "Locate ready; background sync may lag recent edits."` and `locate.reason: "syncing_stale_ok"`. This appeared naturally while the background keeper was re-indexing a file I'd just created (this very docs file) — `keeper.dirty.paths` listed it by name with a `disk_poll` reason and a live processing state that transitioned from `"processing"` to `"overlay_ready"` across two `status` calls a couple minutes apart. That's a materially better signal than a blunt ready/not-ready boolean: it tells you the index is usable but might not reflect your very latest edit yet, without blocking you.

**`collect_hot_context(ids=...)` is a solid escape hatch.** Even while the AST-dependent tools were completely stuck (see below), passing an explicit `file::symbol` id directly to `collect_hot_context` worked instantly and returned the correct source body. That's a reliable way to get a body without waiting on AST hydration, as long as you already know the id — which you usually do, straight out of a `map` card.

### What's worse — a real regression

In the previous session, `pack_context` never depended on the AST bundle — only `expand_context` and `collect_hot_context`'s graph-neighbor path did. That was explicitly one of the good properties I called out: "map/pack_context stay available" even when AST hydration stalls.

That's no longer true in 0.3.109. In this session:

- A multi-seed `pack_context` call (`seed_file` + `seed2_file` + `seed3_file`) returned `{"ok":false,"error":"ast_warming", ...}`.
- I retried per its own hint, waited 8s, retried again — same `ast_warming`.
- I then tried the **simplest possible case**: a single-seed `pack_context` with no seed2/seed3 — the exact call shape that worked instantly (`elapsed_ms: 0.3-278`) in the previous session. It also returned `ast_warming`.
- I checked `status` directly: `ast_hydrated: false`, `warm_elapsed_ms: 162235.1` (162 seconds) — already well past the engine's own `warm_deadline_ms: 90000` (90 second) budget, with `runtime_state: "READY"` reported everywhere else.
- I waited another 30 seconds and retried `pack_context` a third time. Still `ast_warming`. Total: over 3 minutes of real wall-clock time, never once resolving, on both single- and multi-seed shapes.

So the previous session's finding — "AST hydration can stall independently of general readiness, and it specifically blocks `expand_context`/`collect_hot_context` while `map`/`pack_context` stay usable" — has gotten **worse**, not better. `pack_context` is now gated on the same flaky AST bundle, meaning the one part of the ladder that was previously a dependable fallback is no longer dependable. If this AST stall pattern reproduces for other users on other repos, it would mean the *entire* pack/expand/collect side of the ladder can go dark at once, leaving only `map` (which returns raw ranked cards, not the curated heatmap) as a working locate tool.

### A newly found crash bug (with root cause)

While the AST bundle was stuck warming, I called `expand_context` (both `direction=broad` and the default `direction=all`) on a valid, real seed. Instead of the same clean `{"ok":false,"error":"ast_warming", "hint":"..."}` payload that `pack_context` was correctly returning, it crashed with a raw, unhandled Python exception leaking through the MCP boundary:

```json
{"ok":false,"error":"'NoneType' object has no attribute 'get'", ...}
```

This reproduced identically on two separate calls (different `direction` values), so it's not a transient race — it's a deterministic bug on this code path. I traced it to the actual source rather than guessing. In `packages/pipeline/mcp_locate.py`, the AST-miss handling in `expand_context` does:

```python
hyd = hydrate_ast_bundle(repo, bake_on_miss=False)
hyd_ms = round((time.perf_counter() - t_hyd) * 1000, 1)
if not ast_cache_ready(repo):
    ...
    return _err(
        "expand_context",
        "ast_warming",
        hint=(
            f"AST bundle not ready (hydrate={hyd.get('source') or hyd.get('error')}, "
            f"{hyd_ms}ms). Background bake started — retry expand_context in a few "
            "seconds; map/pack stay available."
        ),
        status="warming",
        hydrate_ms=hyd_ms,
    )
```

`hydrate_ast_bundle(...)` can return `None` (that's exactly what happened in my repro), and the very next line unconditionally calls `hyd.get(...)` without a None-check. That's a one-line bug: `hyd.get('source') or hyd.get('error')` needs to guard for `hyd is None` first (e.g. `(hyd or {}).get('source') or (hyd or {}).get('error')` or an explicit `if hyd is None: ...`). The comment embedded in that same hint string — "map/pack stay available" — is itself now stale, since this session showed `pack_context` failing the same AST-miss condition (just without the crash, because `pack_context`'s equivalent code path apparently does guard against `None` correctly, or takes a different route).

I did not patch this myself since it wasn't asked for, but the fix is small, precisely located, and low-risk if the maintainers want to apply it.

### Timing notes from this session

- First `map` call of the session: `embed_ms: 316.2`, `retrieve_ms: 59.1`, but `elapsed_ms: 8463.4` — roughly 8 seconds unaccounted for beyond the two measured phases. Second `map` call, same session, same warm engine: `embed_ms: 103.1`, `retrieve_ms: 65.7`, `elapsed_ms: 386.5` — back to the normal sub-second range seen previously. So the first call absorbed a real, one-time cost (most likely the new hybrid bm25+graph index doing first-touch setup) rather than this being a sustained slowdown. Worth knowing: the *first* `map` call after a session/engine transition can cost multiple seconds even though `status` already reports `ready`.
- `workspace show`/`pin`/`clear` and `gate`/`status` continued to work normally and quickly throughout, unaffected by the AST stall — consistent with last session's finding that these don't touch the AST lane.

### Updated bottom line

The retrieval quality genuinely improved (hybrid bm25+dense+graph is a real step up, and the new `agent_ready: "stale"` state is a better-designed signal than a binary ready flag). But the core reliability problem from last time didn't just persist, it spread: the AST-hydration stall that used to be contained to `expand_context`/`collect_hot_context` now also blocks `pack_context`, and one of the paths through that stall throws an unhandled `NoneType` crash instead of degrading cleanly. Anyone relying on the "map/pack always work even if AST is stuck" property from before should re-verify it on their own repo — it did not hold in this session, on this repo, across three separate retries spanning over three minutes.

---

## 8. Third pass: confirming the regression and the crash are real (not flukes)

The user asked me to "try again" and rewrite the experience, so rather than assume the previous findings were correct, I re-ran the same checks from scratch in a new pass to see if anything had changed and to confirm the findings weren't one-off noise.

### Version check

`scubiee --version` reported `0.3.109` — identical to the previous session, no new auto-upgrade this time. Same daemon, same session id (`kiro@conn-d23380`), `warm_elapsed_ms` now at `457425.9` (over 7.5 minutes of continuous uptime on this engine instance) and `ast_hydrated` still `false`. So this is not a fresh-boot warmup problem — this specific daemon instance has been up and semantically ready for a long time while never once completing AST hydration.

### Confirming the `pack_context` regression

I ran a fresh `map` query (unrelated wording, different seeds than before) to get new candidates, then fed those straight into `pack_context` with two seeds (`hydrate_ast_bundle` + `start_ast_hydrate_bg`):

```json
{"ok":false,"tool":"pack_context","error":"ast_warming","status":"warming",
 "hint":"AST bundle is still loading. Retry pack_context; do not treat a previous map as this pack."}
```

Same failure, same shape, as the previous session — confirming this isn't specific to the seeds I happened to pick last time. `pack_context` is reliably blocked on AST hydration on this repo right now, not intermittently.

### Confirming the `expand_context` crash

I called `expand_context` again, on a *different* seed (`hydrate_ast_bundle` in `context_trace.py`, versus `_attach_warm_coordinator` in `mcp_lifecycle.py` last time), with `direction=all`:

```json
{"ok":false,"error":"'NoneType' object has no attribute 'get'"}
```

Identical crash signature, on a different symbol, different query, different `map` seed. That rules out "this only happens for that one specific function" — it's a general property of the AST-miss handling path in `expand_context`, exactly matching the root cause traced previously (`hyd.get(...)` called without checking `hyd is None` in `packages/pipeline/mcp_locate.py`).

### The escape hatch still holds, and turned out even more useful than noted before

`collect_hot_context(ids=["packages/pipeline/context_trace.py::hydrate_ast_bundle"])` worked instantly and, this time, returned the **entire function body** (69 lines, `context_trace.py:518-587`) — not just a snippet. Reading it directly explained the shape of the bug precisely: `hydrate_ast_bundle` only returns an explicit `{"ok": True, "source": ...}` dict on the cache-hit or bundle-hit branches. On a genuine cold miss (no cache, no bundle to load), the function presumably falls through toward a full-bake branch or an implicit `None` — and that's exactly the value that `expand_context`'s `hyd.get(...)` call chokes on. `expand` (by handle) returned the same body via the `file::symbol` handle format, confirming that path is equally reliable.

`gate`, `status`, and `workspace show` all continued to behave exactly as in every previous pass — instant, clean, and correctly tracking session heatmap/query history across calls.

### What this confirms

Nothing changed between the two passes — same version, same bug, same regression, reproduced on different seeds and queries. This was not a fluke of the first attempt:

- **The `pack_context` AST-gating regression is real and persistent.** It is not intermittent; across two independent sessions, multiple retries, multiple wait intervals (up to several minutes), and different seed symbols, `pack_context` has not once succeeded on this repo while `ast_hydrated` is `false`. Given that `ast_hydrated` has also never once flipped to `true` across either session despite the engine being fully `READY` for 7+ minutes, this looks less like "AST is slow to warm" and more like **AST hydration is stuck and not converging on this repo at all** in 0.3.109.
- **The `expand_context` NoneType crash is deterministic**, not a race condition — it reproduces on any seed while the AST-miss condition holds, because the bug is a missing null-check on every call path through that branch, not something timing-dependent.
- **`map` and `collect_hot_context(ids=...)` remain fully reliable** through all of this — both passes confirm these two are safe to lean on even when `pack_context`/`expand_context` are down. `collect_hot_context` with explicit ids is, in practice, the most dependable way to get a real source body on this repo right now.

### Practical guidance that falls out of this

If you're using Scubiee 0.3.109 on a repo where `pack_context` keeps returning `ast_warming` no matter how long you wait: don't keep retrying `pack_context` or `expand_context` — go straight from `map`'s card `loc`/`file::symbol` ids to either a native file read or `collect_hot_context(ids=[...])`, which bypasses the stuck AST path entirely and has been 100% reliable across both sessions of testing.

---

## 9. Fourth pass: the update actually fixes both issues (0.3.109 → 0.3.110)

The user updated Scubiee and asked me to try it again. `scubiee --version` now reports `0.3.110` — one patch release past the version both prior regressions were confirmed on. New engine session (`kiro@conn-21f230`), same repo.

### Re-testing both known issues

**`pack_context` — fixed.** Ran the exact same seed (`hydrate_ast_bundle` in `context_trace.py`) that reliably produced `ast_warming` across two prior sessions. This time it succeeded immediately:

```json
{"ok":true,"tool":"pack_context", "elapsed_ms":154.0,
 "timing":{"load_repo_ms":0.2,"poly_ms":[15.1],"merge_ms":0.0,"cards_ms":111.9},
 "sla":{"target_ms":5000,"elapsed_ms":154.0}}
```

Notably it returned 16 heatmap cards via real call-graph traversal (`poly_ms: 15.1`, non-zero — meaning the polytrace/graph step actually ran, not just a dense-similarity fallback), pulling in genuinely connected code across `packages/trace_lab/facts/`, `packages/trace_lab/policy/`, and `packages/trace_lab/engine/` — a much richer graph-based result than any `pack_context` call in the previous two sessions produced, all of which had either failed outright or returned thin, dense-only heatmaps.

**`expand_context` — fixed.** Same call shape that previously crashed twice with `'NoneType' object has no attribute 'get'` (same seed, `direction=all`) now returns cleanly:

```json
{"ok":true,"tool":"expand_context","elapsed_ms":0.5,"hydrate_ms":0.4,"hydrate_source":"cache","count":10}
```

Ten real graph-neighbor cards, no crash, sub-millisecond.

### Confirming *how* it was fixed, not just *that* it was fixed

Rather than take the absence of an error at face value, I pulled the actual updated source via `collect_hot_context(ids=["packages/pipeline/context_trace.py::hydrate_ast_bundle"])` to see what changed. The function itself was fixed at the root, not patched around at the call site. In the version I inspected during the crash investigation, the cold-miss path's return value was unclear/implicit; in this version, `hydrate_ast_bundle` explicitly returns:

```python
if not bake_on_miss:
    return {
        "ok": False,
        "source": "miss",
        "error": "miss",
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }
```

So the fix is at the actual source of the problem: `hydrate_ast_bundle` now always returns a real dict — with an explicit `"ok": False, "source": "miss", "error": "miss"` shape on a genuine cold miss — instead of implicitly falling through to `None`. That means the `hyd.get('source') or hyd.get('error')` call in `expand_context`'s error-hint formatting (the exact line identified as the root cause two sessions ago) now always has a real dict to call `.get()` on. This is the correct fix: harden the function that produces the value, not just guard every caller that consumes it. I also noticed a related rename in `map` results — `start_ast_hydrate_bg` (0.3.109) is now `_kick_ast_bundle_hydrate` (0.3.110) in `mcp_lifecycle.py`, suggesting the AST-hydrate kickoff path was touched as part of the same fix, not just the miss-handling branch.

### Full ladder re-check

With both known issues cleared, I re-ran the remaining tools to confirm nothing regressed elsewhere:

- `status` — `agent_ready` is back to `"yes"` (it had been stuck at `"stale"`/blocked in the prior session); engine `healthy: true`, `runtime_state: READY`.
- `collect_hot_context(ids=...)` — still instant and correct, returned the full updated function body.
- `expand` (by handle) — still instant and correct.
- `workspace show` — heatmap correctly accumulated hits/heat across the `map` → `pack_context` → `expand_context` sequence in this session, roles (`map`, `pack_context`) tracked per file as expected.
- `gate` — instant, clean, no restart this time.

One thing still unresolved, worth flagging precisely: `status.ast_hydrated` itself still reported `false` even after `pack_context`/`expand_context` both succeeded with `hydrate_source: "cache"`. That specific top-level flag may not be getting flipped/refreshed promptly even though the underlying capability is clearly working now — a minor telemetry lag, not a functional problem, but worth noting since I relied on that exact flag as a signal in earlier sessions.

### Updated bottom line

This update genuinely resolves both real defects found in the previous two passes: the `pack_context` AST-gating regression and the `expand_context` `NoneType` crash. Both were re-tested with the identical seed/symbol/call shape that reliably reproduced them before, and both now succeed cleanly, quickly, and with richer (graph-traced, not just dense) results than what `pack_context` produced even back when it "worked" two sessions ago. The fix appears to be a real root-cause change in `hydrate_ast_bundle`'s cold-miss return contract, not a superficial patch. The only loose end is that `status.ast_hydrated` doesn't yet reflect the improved reality — everything downstream of it works, but that one flag hasn't caught up.

---

## 10. Fifth pass: full re-test of everything on 0.3.112, and the maintainers' own changelog confirms the findings

The user asked me to test everything again after the update. The daemon had auto-upgraded again — `scubiee --version` now reports `0.3.112`, two patch releases past the `0.3.110` tested in section 9.

### The changelog matches my findings exactly

Rather than just probing behavior, this time I read the actual release notes shipped in the repo (`packages/pipeline/upgrade_releases/v0_3_110.py`, `v0_3_111.py`, `v0_3_112.py`) to see what the maintainers say they changed. All three land squarely on what I'd reported:

- **0.3.110** — *"AST hydrate finishes, and expand no longer crashes on a miss."* Notes: "A cold AST bundle now bakes to completion... expand_context no longer crashes when hydrate returns nothing, and pack_context can proceed once that bake lands." This is precisely the `pack_context` AST-gating regression and the `expand_context` `NoneType` crash from sections 7-8, described almost verbatim.
- **0.3.111** — *"status.ast_hydrated matches a warm AST cache."* Notes: "A successful pack or expand no longer leaves that status bit false." This is precisely the loose end flagged at the end of section 9 — `ast_hydrated` staying `false` even after `pack_context`/`expand_context` worked.
- **0.3.112** — *"status flags match the capability they name."* Tightens `ast_hydrated`/`agent_ready`/`warm_ready` semantics further (e.g., "a missing warm_state is unknown, not ready").

I take this as strong external confirmation that the defects traced in this document were real, correctly diagnosed, and specific enough to map onto actual fix commits — not artifacts of my own testing methodology.

### Fresh full-ladder run on 0.3.112

New engine session (`kiro@conn-9f74d0`). First `status` call showed the keeper mid-catch-up: it had detected 13 real changes since the last session (my own doc edits, plus Scubiee's own source changes across the v0.3.110-112 upgrade files) via `disk_poll`, and was actively re-syncing them — `sync_state: "syncing"`, `agent_ready: "stale"`, with `keeper.last_probe.added`/`modified` listing the exact changed paths. This is the "stale but usable" design working as intended: I could keep working through it.

Ran every tool against fresh queries and seeds (not reusing the exact ids from section 9, to avoid just re-confirming a cache hit):

- **`gate`** — instant, clean.
- **`map`** — `elapsed_ms: 801.4`, normal range, correctly surfaced the three upgrade-release files plus several older ones by dense similarity.
- **`pack_context`**, this time with **two seeds** (`_kick_ast_bundle_hydrate` + `RuntimeController._hydrate_ast`) to stress the multi-seed path harder than in any prior session: succeeded in `elapsed_ms: 2325.3` against an `8000ms` SLA, used the `multi_seed_v1` "agreement corridor" engine (`agreement_n: 248`), correctly resolved the second seed to its fully-qualified `ClassName.method` form (`RuntimeController._hydrate_ast`) even though the seed symbol given was ambiguous, and returned a 16-card heatmap with real polytrace timings on both seeds (`poly_ms: [14.7, 13.6]`).
- **`expand_context`** with `direction=callers` (narrower than the `all`/`broad` I'd used before): correctly filtered to real caller relationships only, `elapsed_ms: 35.0`, `hydrate_source: "cache"`. While reading the delta I noticed `start_ast_hydrate_bg` (the function seen in 0.3.109) still exists alongside the newer `_kick_ast_bundle_hydrate` — so that earlier "rename" I'd guessed at was actually a new function added, not a rename; both coexist in the current codebase.
- **`collect_hot_context`** — first tried with bare file paths (no `::symbol`) to see how it handles malformed ids: got back a clean `{"ok":true,"pack":[],"count":0,"empty_bodies":true,"hint":"..."}` rather than an error or a crash — correct, graceful handling of bad input. Retried with proper `file::symbol` ids from the pack heatmap and got two full, correct bodies back, respecting `max_chars` truncation on the longer one.
- **`workspace show`** — heatmap correctly tracked hits/heat/roles across the whole `map`→`pack_context`→`expand_context` sequence in this fresh session.
- **`expand`** by handle — returned `_kick_ast_bundle_hydrate`'s body, which incidentally revealed a second layer of hardening beyond the 0.3.110 fix: the function now wraps its call to `hydrate_ast_bundle` in a try/except and returns `{"ok": False, "error": str(exc), "source": "error"}` on any exception, rather than letting one propagate. That's defense in depth on top of the root-cause fix — even if some future code path made `hydrate_ast_bundle` misbehave again, this wrapper would catch it before it reached the MCP boundary.
- **`workspace clear`** — reset cleanly as always.

Final `status` check after all of this: `agent_ready: "yes"`, `sync_state: "ready"` — the keeper had finished catching up on its own during the test run, and the earlier `"stale"` state resolved itself without any intervention, exactly as its own design promises.

### Conclusion after five passes

Across five testing passes spanning versions 0.3.89 through 0.3.112, the pattern has been: find a real, reproducible issue, describe it precisely with a traced root cause, and watch it get fixed in a subsequent release — with the fix note in the changelog matching the issue almost word for word. On this most recent full pass, every one of the eight tools (`gate`, `status`, `map`, `pack_context` single- and multi-seed, `expand_context` in multiple directions, `collect_hot_context` with both malformed and valid ids, `workspace` show/clear, `expand` by handle) worked correctly, including edge cases I hadn't tried before (multi-seed agreement corridor, narrow-direction expand, malformed collect ids). No crashes, no unresolved stalls, no silent wrong answers. The tool is in noticeably better shape now than at any point in this document's history, and — unusually for this kind of review — the improvement is independently corroborated by the project's own changelog rather than just my own before/after comparison.

---

## 11. Dedicated bug hunt: fuzzing all eight tools on 0.3.112

The user asked for a thorough test aimed specifically at finding bugs, rather than confirming happy-path behavior. This section deliberately fuzzes every tool with malformed inputs, boundary values, injection-style strings, and concurrent calls. Baseline: `scubiee 0.3.112`, same daemon/session as section 10 (`kiro@conn-9f74d0`), engine healthy and `ready`.

Worth noting up front: this fuzzing surfaced the project's own internal adversarial test files — `tests/_mcp_break_it_suite.py` ("Adversarial / multi-agent MCP break-it suite"), `tests/test_mcp_ship_preprod.py::test_concurrent_map_calls_no_raise`, and `scripts/scubiee_mcp_reliability_audit.py` — confirming the maintainers already stress-test concurrency and adversarial input. I did not run these scripts (they're the maintainers' internal tooling); the bugs below come from probing the live MCP tools directly, the same way an agent actually would.

### Bug 1 — `map` returns stale `embed_ms`/`retrieve_ms` on cached repeat queries

`map` appears to cache full result payloads keyed by query text. On an exact repeat of the same query, the response is byte-identical in every field **except** `elapsed_ms` — including the `timings.embed_ms` and `timings.retrieve_ms` sub-fields, which stay frozen at whatever they measured on the *first* call.

Reproduced independently three times, including once under genuine concurrent load:

```
Call 1 (fresh query): embed_ms=132.3  retrieve_ms=251.2  elapsed_ms=713.9
Call 2 (identical query, repeated): embed_ms=132.3  retrieve_ms=251.2  elapsed_ms=86.3
```

```
Call 1 (different fresh query, fired in parallel with call 2): embed_ms=114.0  retrieve_ms=234.7  elapsed_ms=661.3
Call 2 (same query, same parallel batch):                       embed_ms=114.0  retrieve_ms=234.7  elapsed_ms=574.3
```

`elapsed_ms` correctly reflects the much faster cache-hit path (86ms vs 714ms in the first pair); `embed_ms`/`retrieve_ms` do not — they're replayed verbatim from the cached payload rather than being (re)measured, or zeroed/omitted, on a cache hit. Anyone using these two sub-fields to reason about live embedding/retrieval performance — which I did throughout sections 1-10 of this document — would be drawing conclusions from stale numbers whenever a query happens to hit the cache. This is a correctness bug in observability data, not a functional break: results are still correct, just the self-reported timing breakdown is misleading on repeats.

### Bug 2 — `pack_context` leaks an unwrapped internal error when `seed_symbol` is given without `seed_file`

Every other error path in this MCP surface returns a structured `{"ok": false, "tool": "...", "error": "...", "hint": "..."}` envelope — including `pack_context`'s own "seed not found" error for a bad `seed_file` (tested in this same session, see below). But calling `pack_context` with only `seed_symbol` set and no `seed_file` bypasses that envelope entirely:

```
Call: pack_context(mode="lean", seed_symbol="some_symbol_with_no_file", query="...")
Response: MCP tool error: Error executing tool pack_context: 1 validation error for pack_implArguments
seed_file
  Field required [type=missing, input_value={'mode': 'lean', 'seed_sy...nloads\\context-engine'}, input_type=dict]
    For further information visit https://errors.pydantic.dev/2.13/v/missing
```

Two problems: it's a raw, unwrapped string rather than the tool's normal JSON contract (so any caller parsing `{"ok": ...}` would get nothing to parse), and it leaks the internal implementation symbol `pack_implArguments` — the private function name behind the public `pack_context` tool — directly to the caller. That's an internal detail that shouldn't be part of the public error surface.

For contrast, the correctly-behaved version of a bad seed (tested moments earlier in the same session) is clean:

```
Call: pack_context(mode="lean", seed_file="packages/pipeline/totally_fake_nonexistent_module_xyz.py", query="...")
Response: {"ok":false,"error":"seed not found: file='packages/pipeline/totally_fake_nonexistent_module_xyz.py' symbol='' line=0",
           "hint":"Pass seed_file + seed_symbol or seed_line covering a function.", ...}
```

Worth flagging as good news alongside this: that second example also confirms the `pack_context`-accepts-nonexistent-seed-file bug documented in section 4 of this file is now fixed — a nonexistent `seed_file` is correctly rejected rather than being ranked as a hot heatmap card. That regression is resolved; this new leaking-error bug is a different, narrower gap in the same neighborhood (missing companion argument rather than a bad value for a given argument).

### Bug 3 — stale AST span for `create_mcp` contradicts `status`'s own freshness claim

While fuzzing `expand_context`'s `direction` parameter (see below), a returned card pointed at a span that doesn't exist:

```
Call: expand_context(seed_file="packages/pipeline/mcp_locate.py", seed_symbol="ReadArgs", direction="not_a_real_direction")
Response includes delta card: {"id":"packages/pipeline/mcp_locate.py::create_mcp",
                                "loc":"packages/pipeline/mcp_locate.py:3022-6070", ...}
```

I verified directly against the file on disk:

```
Get-Content packages/pipeline/mcp_locate.py | Measure-Object -Line
Lines: 5579
```

The reported span's end line, `6070`, is **491 lines past the actual end of the file**. I re-triggered the same lookup a few minutes later via `collect_hot_context` and got an even more divergent number for the exact same symbol:

```
Call: collect_hot_context(threshold=-5)  [returns everything in the session heatmap, ignoring the threshold]
Response includes: {"id":"packages/pipeline/mcp_locate.py::create_mcp",
                     "loc":"packages/pipeline/mcp_locate.py:3022-6109", ...}
```

`6109` this time — 530 lines past EOF, and *different from the 6070 seen minutes earlier for the identical symbol in the identical file*. I confirmed `create_mcp`'s actual start line (3022) is correct — it's a real factory function that defines every MCP tool as a nested closure, so a large body is plausible — but its true end is constrained by the file's real length; the file's last line (5579) sits in the middle of a nested closure inside `expand_context`'s AST-miss handling, nowhere near either reported end line.

I then checked `status` at the same moment:

```json
{"agent_ready":"yes","agent_ready_note":"Locate and index are ready; map/pack_context reflect current repo state.","sync_state":"ready", ...}
```

This is the more serious half of the bug: the tool is not just returning a wrong span, it is actively asserting that the index reflects current repo state while doing so. A caller has no signal telling them this particular symbol's boundaries are unreliable — `status` gives a clean bill of health for the whole repo. This looks like a **stale AST cache issue for one specific symbol** that survived past a sync that otherwise reports itself complete, rather than a systemic staleness problem (`map`/`pack_context` results elsewhere in this session were consistently accurate). But because it presents as a confident, well-formed answer rather than an error, it's the kind of bug that's easy to act on without noticing — anyone following the tool's own "Native-Read top heatmap loc spans" instruction for this card would read past the end of the file or get truncated/wrong content depending on how their read tool handles an out-of-range end line.

Separately, and lower severity: `expand_context`'s `direction` parameter accepts any string at all — `"not_a_real_direction"` was accepted silently and echoed back in the response (`"direction":"not_a_real_direction"`) rather than being validated against the documented set (`callees|callers|effects|config|broad|all`). It didn't affect correctness of the (valid) results returned, but it means a typo in `direction=` fails silently instead of erroring.

### Bug 4 — `workspace(action="pin")` accepts nonexistent file paths

```
Call: workspace(action="pin", path="packages/pipeline/this_file_absolutely_does_not_exist_anywhere.py")
Response: {"ok":true,"tool":"workspace","action":"pin","pins":["packages/pipeline/this_file_absolutely_does_not_exist_anywhere.py"], ...}
```

No existence check at all — the bogus path is accepted and stored in `pins`. This is the same class of gap that `pack_context`'s `seed_file` validation *used* to have (and has since fixed, per Bug 2's contrast case above) — but `workspace pin` was apparently not covered by that same fix. It's low severity (a pin is just a hint for future session context, not something that gets read from disk immediately), but it's an inconsistency: two different tools in the same MCP surface that both accept a "repo-relative file path" argument now disagree on whether that path needs to exist.

For contrast, the tool's other validation is solid: an empty `path` is correctly rejected (`{"ok":false,"error":"path required for pin", "hint":"workspace(action=pin, path='pkg/x.py')"}`), and an invalid `action` value is correctly rejected via a proper Pydantic `Literal['show','pin','clear']` check — including reassuringly rejecting a deliberately alarming test value (`action="delete_everything"`) rather than silently no-op'ing or, worse, doing something destructive.

### Bug 5 — `expand`'s `max_chars` budget is ignored for values `<= 0`

```
Call: expand(handle="packages/pipeline/mcp_locate.py::ReadArgs", max_chars=0)
Response: full untruncated 1059-character body

Call: expand(handle="packages/pipeline/mcp_locate.py::ReadArgs", max_chars=-100)
Response: full untruncated 1059-character body (identical to above)

Call: expand(handle="packages/pipeline/mcp_locate.py::ReadArgs", max_chars=50)
Response: correctly truncated body, ending with "…"
```

`max_chars=50` truncates exactly as expected, which isolates the bug precisely to the `<= 0` boundary: a budget of `0` or any negative number is being treated as "no limit" rather than "return (approximately) nothing" or being rejected outright. The likely root cause is a falsy-value check in the implementation (something like `if max_chars: apply_truncation()`, where `0` is falsy in Python and skips the branch entirely — and a negative number presumably reaches the same code path without a `>= 0` guard beforehand). Low severity on its own — no caller has a real reason to pass `0` or a negative budget — but it's a genuine, clean, three-point-reproducible boundary bug.

### What did not break

Worth recording the negative results too, since a bug hunt should show what was actually tried, not just what failed:

- `map`: `k` outside `[1, 25]` (tested `0`, `-5`, `999999`) and empty-string `query` are all rejected cleanly via proper Pydantic bounds/length validation with clear error messages — no crashes.
- A SQL-injection/XSS/log4shell/path-traversal-payload query string was accepted safely as plain search text — no injection risk, no crash — though it did trigger the single slowest `map` call observed in this entire document (`elapsed_ms: 8632`, both `embed_ms` and `retrieve_ms` individually elevated well above normal), worth watching if adversarial-looking queries are common in practice, though this could equally be an artifact of it being a distinct/unusual embedding rather than the payload characters specifically.
- `pack_context`: a garbage `mode` value was silently ignored (fell back to default `lean` behavior) rather than crashing — not ideal, but not dangerous. `max_bodies=999999` was gracefully clamped to the number of cards actually available rather than erroring or overallocating.
- `expand_context`: with no seed/node given at all, it correctly fell back to the session's last-touched hot card per its documented behavior.
- `expand`: a path-traversal-style handle (`../../../../etc/passwd::fake_symbol`) and an empty-string handle were both correctly rejected as "unknown handle" — handle resolution goes through a session-scoped registry rather than raw filesystem path handling, so there's no actual traversal risk even though the string shape looked like an attempt at one.
- Concurrency: five parallel `gate`/`status` calls and two genuinely-parallel identical `map` calls all returned consistent, uncorrupted results with the same session id throughout — no race-condition crashes or cross-talk observed.

### Summary of this pass

Five real bugs found across five different tools, ranging from a cosmetic timing-telemetry inconsistency (Bug 1) to a genuinely concerning stale-index-presented-as-fresh case (Bug 3). None were security-exploitable — every injection/traversal/malformed-input attempt was safely contained — and the validation that *does* exist (bounds checks on `map`, envelope-consistent errors on most paths, handle-registry isolation on `expand`) is generally solid. The gaps are concentrated in inconsistent enforcement across otherwise-similar parameters (`pack_context`'s `seed_file` is validated for existence but `workspace`'s `path` isn't; `max_chars` truncates correctly for positive values but not for zero/negative; `direction` isn't validated against its documented enum at all) rather than in any single badly-designed tool.

---

## 12. Testing through user-facing surfaces only: CLI + live daemon behavior, on 0.3.112

The user asked specifically to find bugs through the actual user-facing tools — MCP and CLI — rather than the internal pytest suite (which can pass or fail against mocked internals that don't reflect what a real user experiences). An initial attempt to run the full `pytest tests/` suite was abandoned for exactly this reason: it requires a from-scratch environment fix (the checked-in `.venv` had no `pip`, the system Python had a broken `opentelemetry`/`logfire` dependency chain unrelated to Scubiee, and many of the ~1683 collected tests need fixtures/hardware not present here), and even a working run would mostly test internal mocked behavior rather than the real CLI/MCP surface a user actually touches. This section instead exercises `scubiee` the CLI binary and the live daemon directly, the same way an actual user would, and documents everything that broke — including one live incident that happened in real time during testing.

### Bug 6 — CLI and MCP disagree on Windows console output; Unicode renders as mojibake

Running `scubiee status .` (human-formatted output, not `--json`) in a default Windows PowerShell window produces garbled box-drawing and checkmark characters:

```
  Γ£ù Engine not running
ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓ
```

This isn't limited to custom-formatted output — it also corrupts argparse's own auto-generated `--help` text:

```
scubiee map --help
  query   Expanded denser code-vocab query (symbols/paths/verbs; ~30û80 tokens)
```

I confirmed the source is correct (`packages/pipeline/__main__.py:2435` has a proper `~30–80 tokens` with a real em-dash) via `grep_search`, which renders it perfectly — so this is not a source-encoding bug, it's a genuine console-output encoding mismatch: `[Console]::OutputEncoding` on this machine is `IBM437` (OEM codepage 437) while the CLI is emitting UTF-8 box-drawing/checkmark/em-dash bytes without setting the console codepage first. Piping the same command through `Out-File -Encoding utf8` and reading it back as UTF-8 produces perfectly clean text, confirming the bytes are correct and only the direct-to-console path is broken. This affects every Windows user running `scubiee` in a default PowerShell window without having manually switched their console to UTF-8 (`chcp 65001` or `[Console]::OutputEncoding = [Text.Encoding]::UTF8`) — likely most users on a fresh machine.

### Bug 7 — `scubiee map` reports `engine_down` for a server that is actually up and serving requests

While the daemon was in the degraded state described below, `scubiee map "<valid query>" .` consistently returned:

```json
{"ok":false,"tool":"map","error":"engine_down"}
```

At the exact same moment, `scubiee search "<same query>" .` against the identical repo succeeded, and the engine log showed the HTTP server actively returning `200` on `/health`, `/v1/open`, and `/v1/search`:

```
127.0.0.1 - "GET /health HTTP/1.1" 200 -
127.0.0.1 - "POST /v1/open HTTP/1.1" 200 -
127.0.0.1 - "GET /health HTTP/1.1" 200 -
127.0.0.1 - "POST /v1/search HTTP/1.1" 200 -
```

So `map`'s own readiness gate is stricter than what the server actually needs to serve a request — it's checking something (most likely the same `warm_phase` state discussed in Bug 8 below) that doesn't accurately reflect the server's real capability, producing a false "down" report for a server that isn't down. A caller seeing `engine_down` from `map` while `search` and raw `/health` both succeed has no way to know the daemon is actually fine — the error message actively points them toward the wrong diagnosis (assume the daemon needs restarting, when in this case it didn't).

Separately: `scubiee map ""` (empty query) reuses this exact same misleading `engine_down` error rather than a clear "query is required" message — the MCP `map` tool, tested extensively in earlier sections, correctly rejects an empty query with `"String should have at least 1 character"`. The CLI and MCP diverge here: MCP correctly identifies bad client input as bad input; the CLI blames the engine for what is actually a client-side validation gap.

### Bug 8 — the daemon can wedge in an infinite `warm_phase:prewarm` loop that its own watchdog does not detect or fix

This is the most serious finding in this session, and it happened live, not as a constructed test case. Partway through this testing pass, the MCP connection dropped (`MCP tool call failed: Not connected`) and `scubiee engine status` simultaneously reported `Engine not running` — while two `pythonw` processes were still alive in the process list at the OS level. I checked the actual TCP port directly:

```
Test-NetConnection -ComputerName 127.0.0.1 -Port 8765
TcpTestSucceeded : False
```

So the process was alive but nothing was listening — a genuine zombie. I ran `scubiee engine start`, which reported success (`{"ok": true, "started": true, "pid": 452, ...}`) and correctly noted `watchdog.already_running: true, restart_count: 0, last_error: null` — meaning the watchdog process was alive throughout this entire incident and never noticed or repaired the dead daemon on its own. The MCP connection did not recover on its own either, even several minutes after the CLI confirmed the engine was healthy again — reconnecting the MCP bridge appears to require an explicit action from the IDE host (Kiro), which nothing in this session was able to trigger; `scubiee heal`'s own output later confirmed this with an explicit hint: *"Reload Scubiee MCP in Cursor after heal."*

Shortly after that restart, the engine tipped into a second, different failure mode: the log filled with an unbroken repetition of the identical line, byte-for-byte, for minutes on end with no state change:

```
[engine] warm contract: action=busy clients=0 idle={'ok': True, 'action': 'busy', 'reason': 'warm_phase:prewarm'}
[engine] warm contract: action=busy clients=0 idle={'ok': True, 'action': 'busy', 'reason': 'warm_phase:prewarm'}
... (repeats indefinitely, clients=0 throughout)
```

`clients=0` the entire time explains why the MCP showed "Not connected" — the daemon's own bookkeeping agreed no client was attached. I ran `scubiee doctor .`, which correctly diagnosed the real problem with a clean, specific repair plan:

```json
"binding": {"ok": false, "healthy": false, "matched": false, "bound_repo": null, "lock_pid": null,
            "repair": "scubiee engine ensure C:\\...\\context-engine  # reopen so soft search binds this workspace"},
"repair_plan": [{"id": "bind_daemon", "kind": "safe", "detail": "scubiee engine ensure ..."}]
```

I ran the exact recommended repair, `scubiee engine ensure .` — **it hung for the full 60-second timeout with zero output**, and the engine log kept repeating the identical stuck `warm_phase:prewarm` line throughout, completely unaffected. `doctor`'s own suggested fix does not work for this failure mode. The command that did work was `scubiee heal .`, which explicitly force-kills stuck processes before restarting rather than trying to gently "ensure" the existing (wedged) one:

```
[scubiee heal] sweeping engine daemons (+0.0s)
[scubiee heal] restoring MCP pins (+2.3s)
[scubiee heal] ensuring daemon (+2.9s)
[scubiee heal] opening repo (+9.0s)
[scubiee heal] reconnecting MCP tools (+9.3s)
[scubiee heal] health check (+9.4s)
[scubiee heal] done ok=True healthy=True (+9.7s)
```

```json
"engine_sweep": {"ok": true, "killed": [8236, 9840, 10740], "remaining_pids": [], "still_healthy": false, "port": 8765}
```

`heal` had to kill three separate stuck PIDs before it could start a clean one — confirming the earlier `engine start` and the watchdog had both left dead/wedged processes behind rather than cleaning them up. This resolved the immediate hang, but the daemon wedged into the exact same `warm_phase:prewarm`/`clients=0` state again within roughly a minute of normal use (a `map` call, followed by a `search` call), and that second `search` call crashed outright with an unhandled `ConnectionResetError: [WinError 10054] An existing connection was forcibly closed by the remote host` — a raw Python traceback printed straight to the console rather than a caught, clean error. A second `scubiee heal .` recovered it again in under 9 seconds.

**Net finding:** this specific repo/session hit a real, reproducible daemon-wedging failure mode — not once, but twice in the same testing session — where the process survives but stops actually serving warm requests, the CLI's own recommended self-repair (`doctor` → `engine ensure`) does not fix it, the watchdog does not detect or repair it despite being alive and reporting no errors the entire time, and one of the two occurrences produced an unhandled exception visible to the user instead of a clean error. `scubiee heal` is the tool that actually works here — reliably, in under 10 seconds both times — but a user would have no way to know to reach for `heal` specifically rather than the more discoverable `engine ensure`/`engine start`/`doctor`-suggested path, since none of those diagnose or fix this state.

### What did not break (CLI side)

- `scubiee --help` and all subcommand `--help` text render correctly in content (aside from the Unicode/mojibake issue in Bug 6, which is a rendering problem, not a content problem).
- `scubiee map "test" nonexistent_repo_path_xyz` correctly rejects a bad repo path with a clear `"not a directory: ..."` error.
- `scubiee doctor .` itself is genuinely good: thorough, well-structured, and it correctly identified both the daemon-binding problem (Bug 8) and an unrelated real issue on its own — `install.binaries_match: false`, flagging that the invoked `scubiee` binary (`~\.local\bin\scubiee`) differs from the one this Python environment would use (`~\AppData\Roaming\uv\tools\scubiee\Scripts\scubiee.exe`), with a specific, correct hint about fixing PATH. That's `doctor` catching a real install-drift issue proactively, independent of anything I was testing for.
- `scubiee heal .` is robust and effective — it correctly force-killed genuinely wedged processes and restored full health in under 10 seconds on both occasions it was needed, including reconnecting the MCP config pins and Cursor/Kiro registrations.

### Summary of this pass

Three more confirmed bugs (6, 7, 8), on top of the five found via MCP fuzzing in section 11 — eight total across this document's two dedicated bug-hunting passes. The most consequential is Bug 8: a live, twice-reproduced daemon-wedging failure that the project's own recommended diagnostic-and-repair path (`doctor` → `engine ensure`) fails to resolve, that the watchdog process does not catch despite running the whole time, and that briefly produced an unhandled crash visible to the end user. `scubiee heal` is the correct remedy and worked reliably both times, but it isn't the tool `doctor` points to, which matters in practice — a user hitting this exact sequence and following the officially suggested repair would stay stuck.
