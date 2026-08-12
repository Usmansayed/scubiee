# Phase R4 — Completeness stress test (seal gaps) + paper toolset

**Date:** 2026-08-10  
**Status:** research complete for R4 — **paper proposal only; do not implement until approved**  
**Inputs:** R1–R3 reports; 16 Cursor trial arms (8 runs); current CE surface `search | read | status`

---

## 1. Native locate patterns observed (Cursor trials)

Counts across the 8 focus runs (CE + raw arms):

| Pattern | Count | Maps to need | What agent is doing |
|---|---:|---|---|
| `native_read` (fullish) | 659 | **N6** | Open file/span for reasoning/edit |
| `native_grep` scoped | 322 | **N3** | Exact/regex in path/glob |
| `native_glob` | 78 | **N4** | Filename / path pattern |
| `native_grep` unscoped | 30 | **N3** | Repo-wide exact/regex |
| `shell_read` (cat/type/…) | 11 | **N6** | Bypass Read tool |
| `shell_grep` (rg) | 5 | **N3** | Bypass Grep |
| `shell_git_read` | 4 | *(defer)* | History/branch context — not code-locate |
| `shell_ls` | 2 | **N1** | Orient (rare in Cursor vs TraceLab) |

**CE arms still leak heavily to natives** even with CE-first instructions: typically **50–80** native locate calls per CE arm (grep+glob+read). Thrash arm cut native reads but kept **grep+glob+shell_rg**.

MCP modes seen: `search` (soft-dominant), `read`, rare `read(neighbors)`. **outline = 0**.

---

## 2. Gap matrix under a hard seal

Assume: agent may use **only** CE for locate; natives allowed **only** if MCP hard-fails. Mutate/verify/shell-tests stay native. Git history stays native for now.

| Need | Required under seal? | Current CE (`search/read/status`) | Gap? |
|---|---|---|---|
| **N1** Orient | Yes (TraceLab first-action; else shell ls) | No | **GAP** |
| **N2** Soft locate | Yes (primary CE value) | `search` | Covered |
| **N3** Hard locate | Yes (27% Cursor; CE arms still Grep) | No dedicated exact tool | **GAP** |
| **N4** Name/path | Yes (Glob common) | No | **GAP** |
| **N5** Structure skim | Yes (cheap pre-read) | Only on `rich` surface; unused | **GAP** (or fold) |
| **N6** Span open | Yes (dominant volume) | `read` | Covered (must stay budgeted + deduped) |
| **N7** Neighbors | Secondary | `read(neighbors=true)` | Covered as **mode** |
| **N8** Session memory | Yes (ROI) | Re-read → `unchanged` stub only | **PARTIAL** — no explicit recall/list |
| **N9** Widen once | Policy | Instruction only | Not a tool — grammar |
| **N10** Stop collect | Policy + eval | Missing / inverted by “ALWAYS read” | Not a tool — grammar + KPIs |
| Git read-only | Out of scope (R0) | — | Escape = native shell |

### Seal blockers (must close before forcing MCP-only)

1. **N3 exact locate** — without it, agents Grep or fail tasks.  
2. **N4 name locate** — without it, agents Glob.  
3. **N1 orient** — without it, agents `ls`/`find` (TraceLab) or Glob cascades.  
4. **N8 recall** — without it, multi-turn re-pays (R1) and post-edit locate tax (R3).  
5. **N10 grammar** — without it, completeness + compliance → thrash (R2/R3).

N5 can be a **mode of span-open** (outline in response / `detail=outline`) rather than its own tool — agents never called outline when it was separate.

---

## 3. Design constraints from R1–R3 (carry into tool count)

| Constraint | Why |
|---|---|
| ≤6 agent-facing tools | User target; instruction &lt;300 tok |
| Cover N1–N8 in tools/modes; N9–N10 in grammar | Completeness + anti-thrash |
| Prefer **modes over twin tools** | outline/neighbors unused as separate discoverables |
| Exact locate **inside** seal | Prior “drop MCP grep” was for soft-insert; seal flips it |
| Unique payload already saturates | Don’t optimize for fatter results — fewer calls, earlier edit |
| Complexity stays server-side | Hybrid index, budgets, dedup, heatmap invisible to agent |

---

## 4. Paper proposal — 5 tools (+ status) = 6

**Working name: sealed retrieval surface `nav`.** Names are provisional.

| # | Tool | Needs covered | Replaces native patterns |
|---|---|---|---|
| 1 | **`search(query, mode?)`** | N2 soft; N3 when `mode=exact` (or auto) | Grep / rg / soft semantic |
| 2 | **`files(pattern\|query?)`** | N4 name; N1 light orient (repo/subtree card) | Glob / ls / find |
| 3 | **`read(target, detail?)`** | N6 span; N5 if `detail=outline`; N7 if `detail=neighbors` | Read / cat / outline / neighbors |
| 4 | **`recall(need?)`** | N8 session memory | Re-Grep / re-Read / “what do we know” |
| 5 | **`expand(handle)`** | N6 materialize stored span at edit time | Full re-read of known span |
| 6 | **`status()`** | Health / surface / session size — not locate | — |

**Why not 3 tools?** Under seal, folding exact+files+recall into `search` recreates ambiguous mega-tool and thrash (agent can’t route).  
**Why not map/focus/workspace alone?** Those assumed native Read for bodies; seal forbids that — need explicit span + exact + files.

### Suggested defaults (server-enforced)

- `search`: default soft; `mode=exact` for literals; always pointer-first (`fetch=false` equivalent); cap k.  
- `files`: returns paths + 1-line blurbs, not bodies.  
- `read`: budgeted span; `detail=outline|body|neighbors`; re-read → stub.  
- `recall` before new `search` on follow-ups (grammar).  
- `expand` only when editing that handle.

### Trajectory grammar (&lt;300 tok sketch — not final copy)

```text
CE nav = search | files | read | recall | expand | status. Locate only here unless MCP errors.

Cold / new topic: files or search → read(best) → edit.
Follow-up: recall → read/expand → edit. New search only if recall empty.
Exact string: search(mode=exact). Known name: files(pattern).
Wiring: read(detail=neighbors). Shape only: read(detail=outline).
Budget: few searches; one read per decision; edit as soon as you can.
Do not re-fetch unchanged spans. Shell = tests/git only.
```

(Word-count to be cut to &lt;300 tok at R5; anti-thrash lines are mandatory.)

### Eval gates before claiming win

- Task success ≥ raw  
- `work_tokens` ≤ raw (fair complete runs)  
- `native_locate ≈ 0` except documented MCP failure  
- `first_edit_step` p50 ≤ efficient band (~60)  
- `pre_locate_calls` not ≫ raw  
- `post_locate_calls` low  

---

## 5. Alternatives considered (not recommended as primary)

| Option | Tools | Weakness |
|---|---|---|
| A. Keep `search/read/status` + ban natives | 3 | **Fails seal** — N3/N4/N1/N8 gaps |
| B. Add only `grep` + `glob` to current | 5 | No recall/expand → multi-turn tax remains |
| C. Classic map/focus/workspace/recall/expand | 5+status | Weak explicit exact/files; historically assumed native Read |
| D. One mega `retrieve(op=…)` | 1+status | Routing errors; thrash risk; bad for &lt;300 tok clarity |

**Recommend §4** as the paper baseline for a sealed A/B surface.

---

## 6. Explicit non-goals for this surface

- Mutate / verify / package installs  
- Git write; git log/blame (native until evidence demands)  
- Web search  
- Forcing a single linear WF1 script for all chats  

---

## 7. Exit criteria for research → design approval

- [x] R1 need coverage (TraceLab)  
- [x] R2 Cursor labels  
- [x] R3 information diet  
- [x] R4 gap list + paper ≤6 tools  
- [x] User approves §4 toolset (or picks alternative) — **approved 2026-08-10**
- [x] R5 instruction grammar + sealed trial harness — design + Tasks 1–5 in plan

**Approved next docs:**
- Design: `docs/superpowers/specs/2026-08-10-sealed-retrieval-nav-design.md`
- Plan: `docs/superpowers/plans/2026-08-10-sealed-retrieval-nav.md`
