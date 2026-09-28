# Scubiee MCP Live Cursor Session Log

**Date:** 2026-08-29  
**Host:** Cursor (Windows), workspace `C:\Users\usman\Downloads\context-engine`  
**MCP namespace:** `user-scubiee`  
**Project id (from disk):** `ce_9d8eb3aef9a744c5ef479299c6666aa5` (`.scubiee/id.json`)  
**Evaluator:** Cursor agent (Grok 4.6)  
**Goal:** Use **only** Scubiee MCP to retrieve code and understand the repo; log every friction point.

This is the live-host follow-up that `docs/scubiee-mcp-eval-v3-retest.md` asked for. Prior v1/v2/v3 evals hit `mcp_locate.py` in-process. This session used the **connected Cursor MCP server**.

---

## Executive summary

**The live MCP session could not retrieve any code.** After `gate(root=workspace)` returned GATE 1 (managed), the host still exposed only `gate`. `map`, `focus`, `grep`, `glob`, `workspace`, `expand`, and `status` were not registered. Calling them failed with "tool not found."

This is a **P0 host deadlock**, not a ranking/truncation issue. Unit tests never catch it: they freeze `_is_repo_managed()` *before* `create_mcp()`, so they never see "unmanaged at process start, managed on a later `gate(root=…)` call."

| Step | Expected | Actual |
|------|----------|--------|
| Catalog at chat start | phase tools if enrolled | `gate` + `mcp_auth` only |
| Namespace instructions | GATE 1 + map/focus trajectory | Frozen `GATE 0:r. Not managed…` |
| `gate(root=workspace)` | JSON with hint + session_id + next tool | Bare string `1:ce_9d8eb3aef9a744c5ef479299c6666aa5` |
| After GATE 1 | `map` / `focus` appear or stay callable | Still only `gate`; `map`/`status` **not found** |
| Repo understanding via Scubiee | map → focus → spans | **0 files, 0 spans** |

Native Grep/Read were used **only after** the MCP deadlock, to diagnose *why* tools were missing — not as a successful Scubiee path.

---

## Protocol the agent followed

1. Discover `user-scubiee` tools (`GetDynamicTools`).
2. Call `gate()` once with Cursor Workspace Path (AGENTS.md + namespace: "User asks Scubiee → gate() once").
3. Follow GATE 1: ban native locate; use `map` | `focus` | `grep` | `glob`.
4. Re-list tools; attempt `map` and `status`.
5. Stop locating via Scubiee; diagnose registration; write this log.

---

## Tool trace (verbatim)

### 1. Catalog — before `gate()`

**Call:** `GetDynamicTools(namespace=user-scubiee)`

**Namespace status:** `ready`  
**Namespace description (injected every turn):**

```
GATE 0:r. Not managed — USE native Grep/Glob/Read/search only; Scubiee locate unavailable. User asks Scubiee → gate() once.
```

**Tools advertised:**

| Tool | Schema notes |
|------|----------------|
| `gate` | `root`, `project_id`, `session_id` — all optional strings, default `""` |
| `mcp_auth` | empty object (host-injected auth stub) |

No `map`, `focus`, `grep`, `glob`, `workspace`, `expand`, `status`.

**UX notes:**

- Description is the unmanaged template from `_minimal_gate_instructions()` (`mcp_locate.py` ~314–318).
- `0:r` means "not managed, TTL elapsed, you may call `gate()` once" — matches `_gate_line()` when `_is_repo_managed()` is false **without** a bound `root`.
- The workspace *is* enrolled on disk. The MCP **process** does not see that until `root=` is passed.

### 2. `gate(root=…)`

**Call:**

```json
{
  "namespace": "user-scubiee",
  "toolName": "gate",
  "arguments": { "root": "C:\\Users\\usman\\Downloads\\context-engine" }
}
```

**Return (entire payload):**

```
1:ce_9d8eb3aef9a744c5ef479299c6666aa5
```

**What the compact line means** (from `_gate_line` docstring): managed; reuse `ce_…` as `project_id` on later locate tools.

**What was missing vs AGENTS.md / phase instructions:**

| Expected field | Present? |
|----------------|----------|
| `hint` (AGENTS.md: "follow the returned hint exactly") | **No** — not JSON, no hint |
| `session_id` (rules: pass it on later calls) | **No** |
| `next` / which tool to call | **No** |
| `managed`, `should_use_mcp` | **No** |
| Tool list | **No** |
| Engine health / warming | **No** |

Token budget succeeded (~1 token line). Agent protocol failed: GATE 1 implies tools that do not exist, with no recovery hint ("reload MCP", "tools not registered", "pass project_id to map").

### 3. Catalog — after GATE 1

**Call:** `GetDynamicTools(namespace=user-scubiee)` again.

**Result:** Unchanged. Still GATE 0 copy. Still only `gate` + `mcp_auth`.

`gate()` does **not** mutate the FastMCP tool list or server instructions. Both are fixed in `create_mcp()` at process start.

### 4. Locate attempts

| Call | Result |
|------|--------|
| `map(query="repo architecture pipeline MCP locate…")` | `Error: Tool user-scubiee-map was not found` |
| `status()` | `Error: Tool user-scubiee-status was not found` |

Host-level miss: the tool is absent from the MCP session, not an application error JSON (`ok: false`, `hint: …`).

No further Scubiee locate calls were made (expand/focus/grep would fail the same way).

---

## Root cause

### A. Tool list is frozen at `create_mcp()`, from unmanaged cwd

```2992:3014:packages/pipeline/mcp_locate.py
    # ---- register per surface ---------------------------------------------
    managed = _is_repo_managed()

    if surface == "phase":
        _tool("gate", "Session gate — ~5 tokens (managed check)", gate_impl)
        if not managed:
            return mcp
        _tool("map", ...)
        _tool("focus", ...)
        ...
```

Cursor's Scubiee MCP is a **long-lived global process**. At spawn, `_default_repo()` is typically the MCP cwd (often home / not this git root). `_is_repo_managed()` is false → **only `gate` is registered**. There is no `notifications/tools/list_changed` path in this repo.

### B. Per-call `root=` can still flip GATE to 1

`gate_impl` binds `root` via `_bind_request_repo`. With the workspace path, it finds `.scubiee/id.json` + registry `managed: true` and returns `1:ce_…`.

After the call, the bind is gone. Instructions and the tool list stay unmanaged.

### C. Unit tests encode the freeze, not the Cursor gap

`tests/test_token_efficient_gating.py`:

- unmanaged at `create_mcp` → tools == `{gate}` (this live session)
- managed at `create_mcp` → full phase toolkit (never true for this Cursor process)

`tests/test_user_journey_scenarios.py` S11: "map not registered unmanaged" — true at register time; **false** after a successful `gate(root=enrolled_workspace)` on the same process.

No test does: `create_mcp()` while unmanaged, then `gate(root=enrolled_repo)`, then assert `map` is callable on that same FastMCP instance.

### D. Instructions are also frozen

`FastMCP(name, instructions=_server_instructions(surface))` runs once. Cursor keeps injecting GATE 0 copy after GATE 1. The agent sees two contradictory sources of truth in the same turn:

1. MCP catalog: GATE 0, native only, locate unavailable  
2. `gate()` result: GATE 1, use Scubiee locate  
3. Project rule (`scubiee.mdc`): GATE 1 bans native Grep/Glob  

That is an instruction collision. The agent cannot satisfy all three.

---

## Agent UX issues (even if tools were present)

These showed up before the missing-tool wall:

1. **No JSON, no hint.** Compact `1:ce_…` is unparseable as a next-action card. AGENTS.md says follow `hint`; there isn't one.
2. **No `session_id`.** Isolation docs require passing it; gate never returns it. Parallel Cursor chats sharing one MCP process is called out in the `session_id` field description — this chat had no id to pass.
3. **`mcp_auth` noise.** Host adds an auth stub on a local server that does not need it.
4. **`root` is easy to omit.** Default `""`. If the agent called `gate()` with no args (namespace says "gate() once"), this process would likely stay `0`/`0:r` even though the folder is enrolled. Passing Workspace Path was necessary and not obvious from the 5-token description.
5. **GATE 1 bans native locate while tools are absent.** Strict compliance = the agent cannot read the repo at all. Loose compliance = it violates the project rule. Either way the product looks broken.
6. **Phase default `max_chars` mismatch in docs vs code.** Instructions say `max_chars=12000`; `focus_impl` default is `6000`. Not hit this session (never reached focus).

---

## What this session could *not* validate

All v3 "live MCP" items remain untested on this host:

- `map` ranking (tests vs `packages/`)
- `focus(outline)` including post-BOM files
- `focus(span)` truncation + `next_start_line`
- `already_in_session` + `expand(handle)` (`text` vs `code`)
- `grep` / `glob` (worktree exclusion)
- `workspace(show)` heatmap
- `focus(query=symbol)` with warm daemon
- `neighbors` vs call graph

v3 in-process regressions may still be green; this log does not contradict them. It says: **Cursor never reached those code paths.**

---

## Repo understanding actually obtained

**Via Scubiee MCP:** none (no cards, no outlines, no spans).

**Via post-deadlock native reads (diagnosis only):**

Scubiee is a local context engine: Merkle sync → Graphify AST → mix compress → embeddings (MLX / FastEmbed) → TurboQuant/FAISS → Conductor ranking.

In-process managers (from README): `RuntimeManager`, `IndexManager`, `ResourceManager`, plus a watchdog.

MCP live surface (intended, phase): `gate` → `map` → `focus` → `grep`/`glob` → `workspace`/`expand`/`status`. Registration is gated on `_is_repo_managed()` at **server construct**, not at **request**.

Relevant packages seen while diagnosing: `packages/pipeline/` (MCP, daemon, session, embed, sync), `packages/graphify/` (extractors/engine), `packages/conductor/` (retrieval), `packages/hybrid_cbm/`, `packages/seir/`, `packages/parse_harness/`.

That is **not** a Scubiee-quality map of the repo. It is leftover from reading `mcp_locate.py` after the MCP failed.

---

## Recommended product fixes (priority)

### P0 — Live Cursor: tools exist after GATE 1

Prefer **always register** phase tools; keep the runtime check inside `map`/`focus`/… (already present). Unmanaged callers get `ok: false` + hint. Token cost is the tool *schemas*, not bodies. Cursor list_tools is cached at connect — hiding tools at construct time makes GATE 1 unreachable.

If schemas must stay hidden when truly unmanaged:

- After `gate()` returns `1:ce_…`, register tools and send MCP `notifications/tools/list_changed`.
- And/or document: Cursor MCP **cwd must be the workspace** (or `CTX_REPO` / `CTX_PROJECT_ID` set at spawn). `gate(root=)` cannot add tools today.

Add a regression that matches this session:

```text
create_mcp() with _is_repo_managed False
→ tools == {gate}
→ gate(root=enrolled_repo) == 1:ce_…
→ map is still missing on that instance  # today's bug
```

Then either flip the assertion (tools should appear) or change registration so the assertion fails until fixed.

### P0 — Resolve GATE 0 instructions vs GATE 1 result

Do not leave catalog text at `GATE 0:r` after a successful managed `gate(root=)`. Options: dynamic instructions, or a one-line hint on the gate payload: `reload MCP / tools not in this process`.

### P1 — Gate payload for agents

Keep the compact line if you want ~5 tokens, but add a second mode or a trailing JSON line:

```json
{
  "gate": "1",
  "project_id": "ce_…",
  "session_id": "…",
  "hint": "Call map(query, project_id=ce_…). Tools: map|focus|grep|glob.",
  "tools_registered": false
}
```

`tools_registered: false` would have ended this session in one hop instead of a deadlock.

### P1 — Test the Cursor spawn shape

Reproduce MCP cwd = home / global, workspace enrolled, agent passes `root=`. That is the default Cursor MCP layout; chdir-to-repo tests hide it.

### P2 — Catalog vs rules

Project GATE rule and MCP instructions disagree whenever registration and `_is_repo_managed()` diverge. One source of truth: if tools aren't listed, instructions must stay GATE 0 (native ok). If gate returns 1, tools must be listed.

---

## Verdict

| Question | Answer |
|----------|--------|
| Is Scubiee MCP connected? | Yes (`user-scubiee`, `namespaceStatus: ready`) |
| Is the repo enrolled? | Yes (`ce_9d8eb3aef9a744c5ef479299c6666aa5`) |
| Did `gate()` detect that? | Yes, **only** with `root=` |
| Could the agent retrieve code via Scubiee? | **No** |
| Blocking bug | Tool registration at `create_mcp()` vs per-call managed bind |
| Safe fallback under GATE 1? | None without violating the project rule |

**Do not treat v3 in-process "expand/BOM/pagination pass" as live Cursor validation until `map` is actually callable in this host after `gate()`.**
