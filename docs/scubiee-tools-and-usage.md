# Scubiee MCP tools and usage (current surface)

> **Current product (v0.3.142+).** Scubiee ships **one MCP tool, `map`, with two configs —
> `find` and `focus`** — plus `gate`/`status` for health. The authoritative definition is
> `packages/pipeline/map_v3_server.py` (`CONFIGS = ("find", "focus")`). The older
> pack/expand/collect/workspace ladder (`mcp_locate.py`) is **retired** and archived under
> `archive/old-mcp-map/`; the pre-v3 version of this doc is at
> `docs/archive/pre-v3-pack-ladder/scubiee-tools-and-usage.md` for history. If this doc and the
> code ever disagree, the code wins.

Scubiee is a **locate layer**, not an editor. Its job is to point an AI coding agent at the
*smallest set of exact code spans* relevant to a task, so the agent reads a few hundred lines
instead of dumping whole files into its context window. The agent still edits with its host's
native tools, and `map` is a **partner to native Grep/Read**, not a replacement.

---

## 1. The surface

| Tool | Config | Use when | Returns |
|---|---|---|---|
| `map` | `find` | You do **not** know where the code lives | Ranked locations **with the relevant code inline**; also orients a wide/unknown area and pulls code near a chunk you hold |
| `map` | `focus` | You **know** the symbol name(s) | That symbol's full body **+ callers/callees + sibling symbols**, in one unit — edit straight from it |
| `gate` / `status` | — | Session start | Health: managed / warming / needs init-or-connect |

**Not Scubiee tools** (use your agent's native ones): exact literal/regex search → **Grep**;
path/filename listing → **Glob**; a known `path:line` read → **Read**; history → **git**. Scubiee
deliberately does *not* wrap these — a one-line grep is faster and more precise than a semantic
search for an exact string.

### Recommended flow
```
status (is the repo ready?) → map find | map focus → edit (native tools) → scubiee sync if needed
```
Pick the config by what you know, act on the first good answer, and stop — never re-search what
`map` already returned.

---

## 2. `map find` — locate by meaning

```json
{"config": "find", "query": "where the token savings summary is computed"}
```
- One intent query → ranked locations. On a confident hit the **enclosing function/class is
  included inline**, so there is usually no follow-up read.
- Also use `find` to **orient** in an unfamiliar area (a broad query) and to **pull code near a
  chunk you already hold** (put its names/intent in the query) — these fold in what used to be
  separate `related`/`graph` configs.
- Returns matched lines with line numbers, a confidence + reason, and — when nothing matches —
  close identifiers and a broader query to try, never a bare empty list.

## 3. `map focus` — a known symbol with its wiring

```json
{"config": "focus", "names": ["compare_queries", "ArmResult"]}
```
- Returns the symbol's **full body + callers/callees + sibling symbol names in one unit** — enough
  to edit from without a follow-up grep. Accepts one or more `names`, or an `anchor`
  (`file::symbol`).
- When you already know a name, `focus` it **first** — don't fold a known-name lookup into a
  semantic `find`.

## 4. Decompose multi-part tasks
A task that needs **two distinct things** is **two calls**, not one bundled query. A broad query
mixing targets returns only the strongest and drops the rest.

---

## 5. Task playbook

| Task | Do this |
|---|---|
| "Where is X handled?" (no names) | `map find(query)` → edit from the inline code |
| "Show me `funcName` and how it's wired" | `map focus(names=["funcName"])` |
| Two unrelated targets | two calls: `find` and/or `focus`, one per target |
| Find every `API_KEY` (exact string) | native **Grep** |
| List `*test*.py` | native **Glob** |
| Read a known `file:line` | native **Read** |
| Recently changed code | native **git** |

---

## 6. Why this saves tokens

The cost model that drives the design: **tokens ≈ context size × number of model calls**, and the
call count is the term that runs away — every extra retrieval round-trip re-reads the whole
transcript (~35–40k tokens in our runs) and keeps paying it on later turns.

1. **Ranked pointers, not file dumps.** `find` returns `loc` + `score` + `why`; a confident hit
   adds just the enclosing symbol, not the whole file. A ranked card list is a few hundred tokens;
   reading the candidate files to find the right one is tens of thousands.
2. **One call finishes the question.** `find` includes the top result's code inline and `focus`
   bundles a symbol's body + wiring, so the common "map → read → grep → read" chain collapses to a
   single call. Spending a few thousand characters once is far cheaper than forcing another ~35k
   round-trip.
3. **Fewer tools, fewer wrong turns.** Two configs (`find` when you don't know where, `focus` when
   you know the name) is almost no decision surface — which is why the surface was narrowed from
   four configs to two in v0.3.142 (usage mining: `find` + `focus` = ~92% of real calls).
4. **Local + incremental.** The index and source stay on your machine; changed files refresh
   incrementally (sub-second) so results stay current without a full reindex.

Measured effect: in a three-turn coding-agent experiment, focused retrieval used ~60–70% fewer
context tokens than the broad-context baseline (varies by repo and task).

---

## 7. Health: `gate` / `status`
One check at session start tells the agent whether the repo is **managed** (enrolled, ready),
**warming** (index building — retry shortly), or **needs init/connect**. On an unmanaged or paused
repo, the agent should use native Read/Grep/Glob instead of locate calls.
