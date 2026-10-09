# Making agents actually follow Scubiee's rules — especially in auto mode

A research-backed playbook for getting coding agents to reliably use the Scubiee `map` tool and
obey its "pick one config, act, stop" discipline instead of falling back to a grep spiral. The
first half is the general strategy (illustrated with Cursor); the **"Cross-tool enforcement"**
section at the bottom makes it portable across Claude Code, Codex, Cursor, Kiro, Pi, OpenCode,
Gemini CLI, Copilot, and more via one shared hook core + thin per-host adapters.

> **Honest framing first.** You cannot *force* a probabilistic model to follow a rule 100% from the
> prompt. Every credible source says the same thing: system prompts and tool descriptions raise the
> probability of the right behavior but are not a hard guarantee. The only way to get
> deterministic behavior is to move enforcement **out of the prompt and into hooks** that can block
> or redirect a tool call. So the playbook is layered: cheap probabilistic nudges first, then a
> deterministic gate for the behavior you truly must enforce.

---

## The four layers (cheapest → strongest)

### Layer 1 — Tool descriptions that teach the model *when* and *how* to call

The model's first (and often only) guide to your tool is the schema + description it sees every
session, from scratch, with no memory of past use.

- **Put a concrete example invocation in the description**, not just prose. A real call like
  `map config=focus names=["pipeline/freshness.py::git_dirty_files"]` beats three paragraphs about
  parameters. Wrong-argument calls are precisely what teach an agent "this tool is broken, back to
  grep" — a practitioner who shipped a code-graph MCP reported wrong-parameter failures dropped the
  day he added a real example call ([dev.to](https://dev.to/emahmoudnabil/my-ai-agent-ignored-my-mcp-server-and-grepped-anyway-three-things-that-actually-fixed-it-193j)).
- **State the "use this when / not when" boundary in the description itself** so the router can
  match intent to tool. Scubiee's current description already says *"Partner to native Grep/Read"* —
  make the boundary sharper: "known literal/path → Grep; unknown location or need wiring → map."
- **Caveat from research: don't over-stuff.** An arxiv study on augmenting MCP tool descriptions
  found that richer descriptions improved task success by a median ~5.85 points **but increased
  execution steps ~67% and regressed 1 in 6 cases** ([arxiv](https://arxiv.org/html/2602.14878v1)).
  So: one example + one boundary line per config, not an essay. (Content rephrased for compliance.)
- **Use MCP tool annotations** (`readOnlyHint`, `idempotentHint`) so well-behaved clients treat
  `map`/`gate`/`status` as safe to auto-execute without a confirmation prompt — removing a
  friction point that pushes agents toward native tools. Note the MCP spec itself says annotations
  are hints, not guarantees, and untrusted clients may ignore them
  ([MCP blog](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)).

### Layer 2 — Rule placement and wording (primacy + recency)

Rules live in the host's rule channel (Cursor **User Rules**, Claude/Kiro steering, `AGENTS.md`).
How and *where* you write them changes behavior measurably.

- **Channel matters more than content.** The Serena+Cursor community setup found that Cursor's
  built-in tool bias overrides file-based rules, and that pasting the rule into **Settings → Rules →
  User Rules** was "the most important step" — global `.mdc` files were not enough
  ([gist](https://gist.github.com/jcpowermac/f3191039cb58cbede817aa0d61cb94d9)). For headless Cursor
  CLI, the equivalent is making sure the rule is actually in the loaded context, not just a repo
  file the router may skip.
- **Exploit primacy and recency.** Long system prompts show primacy bias on guardrails (top) and
  recency bias on instruction-following (bottom). Moving a rule within the prompt is "as load-bearing
  as rewriting it" ([tianpan.co](https://tianpan.co/blog/2026/04/28/prompt-position-policy-shared-system-prompt-ownership)).
  Put the hard "do not re-grep after a map" rule **last**, where instruction-following bias is
  strongest, and the identity/role framing first.
- **Keep it short, specific, testable.** Reliability guidance converges on short, concrete,
  separable rules over a monolithic mega-prompt
  ([evalics](https://evalics.com/blog/why-ai-models-enforce-system-prompts-differently-what-that-means-for-reliability),
  [Medium anti-patterns](https://achan2013.medium.com/agent-anti-patterns-part-5-05da1c3c1828)).
  Our two-layer RULES(<300 tok)/INSTRUCTIONS pattern already follows this — keep RULES to the config
  picker + the stop rule, not a wall of bans.
- **Separate trusted guidance from untrusted data.** Put instructions in a delimited block distinct
  from any pasted code/logs so the model doesn't treat tool output as new instructions
  ([stevekinney](https://stevekinney.com/writing/prompt-engineering-frontier-llms)).

### Layer 3 — Deterministic gates via hooks (the real enforcement)

This is the layer that converts "usually" into "always," and it's what we are missing. Cursor
exposes a hook surface that can **block or redirect** tool calls over stdio JSON
([Cursor hooks docs](https://cursor.com/docs/hooks)). Claude Code has the equivalent PreToolUse
hook; Kiro has `PreToolUse` too.

Relevant Cursor hooks for Scubiee:

| Hook | What it lets us do |
|---|---|
| `beforeShellExecution` (matcher = command regex) | Inspect a shell command; `permission:"deny"` + exit 2 to block a repo-wide `grep`/`rg` and tell the agent to use `map` instead. |
| `preToolUse` (matcher = `Grep`/`Read`) | Same, for the native Grep/Read tools rather than shell. |
| `beforeMCPExecution` (matcher = `MCP:map`) | Observe/shape `map` calls — e.g. reject an empty-config call with a corrective message. |
| `postToolUse` / `afterMCPExecution` | After a `map`, inject `additional_context` ("you now have the heatmap — read these locs, do not re-grep") so the next turn is primed. |
| `sessionStart` | Inject the Scubiee rule into the conversation's initial context so it's present turn 1 (fire-and-forget). |

**The highest-ROI hook: a "grep-guard".** Multiple independent projects implement exactly this and
report it works where rules alone failed:
- Serena's answer to "LSP first, grep last": a PreToolUse hook that **exits 2 to block**, and its
  stderr becomes the model's reason — *"the model then picks another tool on its next step, no
  persuasion involved"* ([Serena discussion](https://github.com/oraios/serena/discussions/1902)).
- `grep-guard` blocks every repo grep while the code-search hub is reachable and hands back the
  exact MCP call to use instead ([codesearch](https://github.com/flupkede/codesearch)).
- `serena-guard` / `claude-no-bash-detour` hard-block file/grep ops and **pre-fill the replacement
  call** (path/pattern already substituted) so the agent just runs it
  ([serena-guard](https://github.com/Lenucksi/serena-guard)).

Design rules for our grep-guard so it helps rather than deadlocks:
1. **Only guard after a `map` has fired this session** (track state in a tempfile keyed by
   `conversation_id`). The first locate can be native if the agent wants; the *re-grep of ground
   map already returned* is what we block. This directly targets the `add_importers` failure where
   the agent grepped 45× and still reached a wrong "file doesn't exist" conclusion.
2. **Allow a fallback escape.** If `map` returned empty/!ok, don't block grep — otherwise you create
   the deadlock the Scubiee rules already warn about.
3. **Return a corrective, machine-actionable message**, not a generic denial: name the config to use
   and the symbol/path. Corrective errors are what let an agent self-fix instead of giving up
   ([dev.to](https://dev.to/emahmoudnabil/my-ai-agent-ignored-my-mcp-server-and-grepped-anyway-three-things-that-actually-fixed-it-193j)).
4. **`failClosed:false`** so a hook crash never bricks the session (Cursor default is fail-open).
5. Match Cursor's `SemanticSearch` tool too, not just Grep — auto agents reach for it in place of
   grep (noted in the Serena setup).

### Layer 4 — Shorten the loop (why tokens stay high even when the rule works)

Even a perfectly-obeyed rule won't cut tokens if the agent takes many turns, because every turn
re-transmits the conversation. One report measured ~80k–120k tokens re-sent per step deep in a
session, so "a simple 4-step tool routine burned 400,000 input tokens"
([dev.to](https://dev.to/julianbrown/how-we-cut-ai-agent-token-usage-by-85-with-local-mcp-1p9o)).
This is why our hard-task cells hit ~2.6M `cache_read` regardless of arm. The levers:
- **Trust-and-stop:** the win only lands if `map`'s result is trusted enough to skip re-verification.
  Layer 3's guard enforces exactly that.
- **Keep tool output out of context ("code mode" / sandboxing):** return compact located spans, not
  dumps; let the agent pull only what it edits
  ([stackone](https://www.stackone.com/blog/mcp-code-mode-agent-context-architecture/),
  [arxiv Tool Attention](https://arxiv.org/html/2604.21816v1)). Scubiee's cards-not-bodies design
  already does this; the risk is the agent re-reading whole files afterward — which Layer 3 blocks.

---

## Recommended rollout for Scubiee (in order)

1. **Add example invocations + sharpen the when/not-when boundary** in each `map` config description
   in `map_v3_server.py` (Layer 1). Cheap, no downside if kept to one line each.
2. **Add `readOnlyHint`/`idempotentHint` annotations** to `map`/`gate`/`status` so clients
   auto-execute them (Layer 1).
3. **Ship a `beforeShellExecution` + `preToolUse(Grep)` grep-guard hook** that activates only after a
   `map` call in the same conversation, with a corrective redirect message and a map-empty escape
   (Layer 3). This is the single biggest lever for the auto-mode re-grep spiral.
4. **Move the "do not re-grep packed ground" rule to the end of the rule block** and confirm it's in
   the host's actual rule channel (Cursor User Rules), not just a repo file (Layer 2).
5. **Add a `sessionStart` context injection + a `postToolUse(map)` reminder** so the discipline is
   present turn 1 and reinforced right after each map (Layers 2–3).
6. **Re-run the Cursor hard-task A/B** (`add_importers_expand_alias`) with the guard on, and measure
   whether the 2.6M `cache_read` collapses while oracle stays 1.0. That's the acceptance test.

## What NOT to do
- Don't rely on stricter prose alone — our own rule-tuning round showed strict prose backfired and
  got *more* expensive.
- Don't hard-ban native tools unconditionally — it causes deadlocks when `map` legitimately has no
  answer. Gate on "map already ran," not "grep is forbidden."
- Don't over-augment tool descriptions — the arxiv result shows diminishing/negative returns past a
  concise example + boundary.

## Sources
- Cursor hooks reference — https://cursor.com/docs/hooks
- Serena + Cursor global setup — https://gist.github.com/jcpowermac/f3191039cb58cbede817aa0d61cb94d9
- Serena "LSP first, grep last" PreToolUse exit-2 — https://github.com/oraios/serena/discussions/1902
- grep-guard / codesearch — https://github.com/flupkede/codesearch
- serena-guard (pre-filled redirect) — https://github.com/Lenucksi/serena-guard
- "My agent grepped anyway — three fixes" — https://dev.to/emahmoudnabil/my-ai-agent-ignored-my-mcp-server-and-grepped-anyway-three-things-that-actually-fixed-it-193j
- MCP tool descriptions arxiv study — https://arxiv.org/html/2602.14878v1
- MCP tool annotations (hints, not guarantees) — https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/
- Prompt position / primacy-recency — https://tianpan.co/blog/2026/04/28/prompt-position-policy-shared-system-prompt-ownership
- System-prompt reliability patterns — https://evalics.com/blog/why-ai-models-enforce-system-prompts-differently-what-that-means-for-reliability
- Context compounding / token cost — https://dev.to/julianbrown/how-we-cut-ai-agent-token-usage-by-85-with-local-mcp-1p9o

_Content from external sources was rephrased and summarized for licensing compliance._


---

# Cross-tool enforcement: making this work on every host, not just Cursor

The Layer-3 grep-guard above was written in Cursor terms. The good news from the research: **almost
every major coding agent exposes the same enforcement primitive** — a "before any tool runs" hook
that blocks by **exit code 2** (or a `permissionDecision:"deny"` JSON) and feeds the reason back to
the model. So one hook design, with a thin per-host adapter, covers Claude Code, Codex, Cursor,
Kiro, Pi, OpenCode, and more. Primary source for the matrix below: the community-maintained
cross-agent reference ([Ar9av/agent-manual](https://github.com/Ar9av/agent-manual)), cross-checked
against each vendor's own docs.

## Per-host capability matrix (the surfaces we rely on)

| Host | Rules file | "Before tool" hook | Block mechanism | MCP intercept | Config format / location |
|---|---|---|---|---|---|
| **Claude Code** | `CLAUDE.md` | `PreToolUse` | exit 2 **or** `permissionDecision:deny` JSON | yes | JSON — `~/.claude/settings.json`, `.claude/settings.json` |
| **Codex CLI/App** | `AGENTS.md` | `PreToolUse` | exit 2 **or** `permissionDecision:deny` JSON | yes (Bash, `apply_patch`, MCP) | TOML `[hooks.*]` in `config.toml` **or** `hooks.json`; `~/.codex`, `.codex/` |
| **Cursor** | User Rules / `.cursor/rules` | `preToolUse`, `beforeShellExecution`, `beforeMCPExecution` | exit 2 + `failClosed` option | yes | JSON — `~/.cursor/hooks.json`, `.cursor/hooks.json` |
| **Kiro** | steering / `AGENTS.md` | `PreToolUse` (+ v2 hooks) | exit 2 | yes | JSON/YAML — `.kiro/hooks/*.json` |
| **Pi (Pi Coding Agent)** | rules | `tool.before.*` / `PreToolUse` | exit 2 | yes | JSON + YAML |
| **OpenCode** | `AGENTS.md` | `tool.execute.before` (plugin) | **throw to abort** | yes | TS/JS plugin module |
| **Gemini CLI** | `GEMINI.md` | `BeforeTool` | exit 2 | yes | JSON |
| **GitHub Copilot** | rules | `preToolUse` | `permissionDecision:deny` JSON | yes | JSON |

Non-hook hosts worth noting: **Warp** and **Aider** don't ship a blocking hook (use rules /
permissions instead); **Trae** can only gate via MCP. For those, you fall back to Layers 1–2 plus
an **MCP-side guard** (below).

## The one honest caveat that shapes the design

Codex's own docs say it plainly: `PreToolUse` *"is a guardrail — [the agent] may still accomplish
equivalent work via another tool path, so do not treat hooks as a complete enforcement boundary."*
([Codex hooks](https://developers.openai.com/codex/hooks)). So even the strong layer isn't airtight
— an agent told "no grep" might `cat` via a different shell path. The design response:
1. Guard the **class** of action, not one tool name — match `grep`, `rg`, `ag`, `find`, `cat`,
   `head`, `tail`, and the host's semantic-search tool, not just "Grep".
2. Keep Layers 1–2 (descriptions + rules) doing the probabilistic steering so the hook is the
   backstop, not the whole plan.
3. Add an **MCP-side guard** for hosts with no hook: the Scubiee server itself can detect a
   re-locate of ground it just returned in the same session and answer with a redirect instead of
   re-searching. That works on any MCP client.

## Universal hook contract (what's actually portable)

Every blocking host converges on the same three-part contract, which is why one script works
everywhere:

1. **Input**: JSON on **stdin** with (at least) the tool name and the tool input/arguments. Field
   names differ (`tool_name` + `tool_input` on Claude/Codex/Cursor; args object on OpenCode) — the
   adapter normalizes these.
2. **Decision**: either **exit code 2** (universally understood as "block") or print a
   `{"hookSpecificOutput":{"permissionDecision":"deny","permissionDecisionReason":"..."}}` JSON
   (Claude/Codex/Copilot/Cursor). Emitting **both** (print the JSON *and* exit 2) satisfies every
   host at once.
3. **Reason**: the blocked reason (stderr for exit-2 hosts, the `*Reason` field for JSON hosts)
   goes back to the model as context so it self-corrects on the next step.

OpenCode is the one shape-shifter: its plugin `tool.execute.before` **throws** to abort rather than
exiting — so it gets a tiny TS wrapper that calls the same core logic and throws the reason.

## Portable implementation: one core, thin adapters

```
scripts/agent-hooks/
  scubiee_guard_core.py     # host-agnostic: reads normalized {tool, args, session_id},
                            #   decides allow/deny, returns (decision, reason)
  adapters/
    claude.py               # stdin JSON -> core -> print JSON + exit 2 on deny
    codex.py                # same contract (Claude-compatible), TOML/json wiring
    cursor.sh/.py           # stdin JSON -> core -> print permission JSON (+ exit 2)
    kiro.py                 # stdin JSON -> core -> exit 2 + stderr
    pi.py                   # stdin JSON -> core -> exit 2
    opencode_plugin.ts      # tool.execute.before -> core (via child proc) -> throw on deny
  state/<session_id>.json   # "has map run this session?" ledger (keyed by conversation/session id)
```

**Core logic (host-agnostic), the only place the policy lives:**
- Maintain a per-session flag `map_ran` (set by a `postToolUse`/`afterMCPExecution` adapter when a
  Scubiee `map` call succeeds, keyed by the host's session/conversation id).
- On a "before tool" event for a **search-class** tool (grep/rg/ag/find/cat/head/tail/semantic
  search) targeting a repo path:
  - if `map_ran` is **false** → **allow** (first locate may be native; never deadlock).
  - if `map_ran` is **true** and the search overlaps ground `map` already returned → **deny** with:
    *"Scubiee already mapped this. Read the loc spans it returned, or call
    `map config=focus names=[...]` / `map config=related anchor=... query=...`. Don't re-grep packed
    ground."*
  - if the last `map` returned empty/!ok → **allow** (escape hatch).
- Everything else → allow.

Because the policy is one Python module, fixing or tuning behavior is a single edit; the adapters
are ~15 lines each and never change.

## Rules + descriptions are still per-host, but share one source

- Keep the Scubiee rule text in **one canonical file** and generate each host's rule file from it:
  `CLAUDE.md` (Claude), `AGENTS.md` (Codex/OpenCode/Kiro), `GEMINI.md` (Gemini), and the Cursor
  **User Rules** paste block. Same content, placed per the Layer-2 primacy/recency guidance.
- The `map` tool **descriptions + annotations** (Layer 1) live in the Scubiee MCP server, so every
  MCP-capable host gets them for free — no per-host work.

## Rollout, revised for cross-tool

1. **Layer 1 (server-side, universal):** example invocations + sharpened boundaries +
   `readOnlyHint`/`idempotentHint` on `map`/`gate`/`status` in `map_v3_server.py`. One change, every
   host benefits.
2. **MCP-side re-locate guard (universal backstop):** the server detects a re-locate of just-served
   ground and returns a redirect. Covers even hook-less hosts (Warp, Aider, Trae).
3. **Portable grep-guard hook** (`scubiee_guard_core.py` + adapters), shipped for the blocking hosts
   (Claude, Codex, Cursor, Kiro, Pi, OpenCode, Gemini, Copilot). Gate on "map already ran," corrective
   message, fail-open on crash.
4. **One canonical rule → generated per-host rule files**, with the stop-rule placed last.
5. **Verify per host** with the same acceptance test (hard cross-file task: tokens drop, oracle
   stays 1.0). Start with Cursor (we have the harness), then Claude Code, then Codex.

## Updated sources (cross-tool)
- Cross-agent hooks/config matrix — https://github.com/Ar9av/agent-manual
- Codex hooks reference (PreToolUse, exit-2 / deny JSON, "guardrail not boundary") — https://developers.openai.com/codex/hooks
- Codex customization / AGENTS.md — https://developers.openai.com/codex/concepts/customization/
- OpenCode plugins (`tool.execute.before`, throw-to-block) — https://docs.dev.opencode.ai/docs/plugins
- OpenCode workflow-guard (deterministic plugin hooks) — https://github.com/ultus-net/opencode-workflow-guard
- Claude Code safety-guard (PreToolUse 3-level override) — https://github.com/inoX-Network/claude-code-safety-guard
- Microsoft Agent Governance Toolkit (OpenCode in-process policy) — https://microsoft.github.io/agent-governance-toolkit/packages/opencode-governance/

_Content from external sources was rephrased and summarized for licensing compliance._
