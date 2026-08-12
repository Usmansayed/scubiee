# Retrieval Trajectory Research (before any 6-tool decision)

**Date:** 2026-08-10  
**Status:** research in progress — **no tool names or surface locked**  
**Owner intent:** Design a small, complete retrieval environment (~5–6 tools) that becomes the agent’s *primary* code-navigation trajectory inside Cursor, with a short instruction (<300 tokens). Natives only if MCP fully fails.  
**Hard rule for this doc:** reason about **retrieval needs**, session evidence, and failure modes. Do **not** pick the final toolset here.

---

## 1. Why this research exists (problem restatement)

Exposing one or two “better” locate tools inside Cursor’s existing Grep/Read/Glob workflow **disrupts** the agent’s natural search trajectory and adds interaction/token overhead.

Observed in CE MCP A/B trials (Cursor SDK):

| Failure mode | What happened |
|---|---|
| Soft insert (CE preferred, natives free) | Agent still Greps/Reads a lot; CE under-used → weak ROI |
| Hard compliance (“ALWAYS CE read”, Grep ≪ 10%) | Agent MCP-thrashes (e.g. 27 search + 72 CE read unique) → **+93% work tokens** vs raw on a fair complete rematch (`20260810T145505Z`) |
| Incomplete surface | When sealed/constrained, any missing capability pushes the agent back to natives or into compensatory loops |

**Thesis to test (not yet proven):**  
If we design a **coherent retrieval toolset** that covers every retrieval job an agent needs (small exact lookup → large structural/semantic locate → deepen → session memory), and we teach a **general trajectory** in &lt;300 tokens, then *forcing* that trajectory (natives only on MCP failure) can beat native Grep/search/read on **task success, tokens, and efficiency**.

Prior designs in-repo (map/focus/workspace; search/read/status) are **hypotheses from TraceLab**, not the final answer for a sealed Cursor environment. This research re-opens the question with two corpora and an explicit “complete coverage under constraint” requirement.

---

## 2. What we already have (inventory)

### 2.1 Corpus A — TraceLab (structural, large-N)

| Asset | Path / note |
|---|---|
| DuckDB | `research/tracelab/raw/syfi_coding_trace.duckdb` |
| 200 session JSON | `research/tracelab/processed/sessions/**` (100 Claude + 100 Codex) |
| Workflow report | `research/tracelab/reports/DETAILED_AGENT_WORKFLOWS.md` |
| Generalized WFs | `research/tracelab/processed/cross/generalized_workflows.json` |
| Savings levers | `research/tracelab/processed/cross/session_savings_levers.json` |
| Framework | `docs/superpowers/specs/2026-08-08-tracelab-context-collection-research-framework.md` |

**Hard facts (from `session_savings_levers.json`):**

- locate + read ≈ **45.8%** of all tool calls (86,728 / 189,425)
- **195 / 200** sessions multi-turn (≥5 user messages)
- ~**614M** total tool `result_chars`
- P50 **~21%** of result chars are duplicate signatures; P90 ~**41%**
- Naive stack (no re-send dups + skip near-dup reads + budget large unused) ≈ **68%** of result chars

**Sanitization limit:** no paths, queries, or message text. Excellent for *roles, sequences, sizes, waste*; weak for *what semantic job* each call was doing.

### 2.2 Corpus B — Cursor SDK CE trials (semantic, small-N)

| Asset | Note |
|---|---|
| `scripts/experiments/sdk_mcp_dev_trial.py` | A/B harness (`ce_*` vs `raw`) |
| Temp run dirs | `C:\Users\usman\AppData\Local\Temp\ce_dev_trial\<ts>\` (`*-arm.json`, `*-conversation.json`) |
| Analyzers | `analyze_trial_session.py`, `analyze_tool_usage.py`, `classify_discovery.py` |

**Hard facts (v6 rematch, model `default`, combo prompt):**

- CE work tokens **4.52M** vs raw **2.34M** (**+93%**)
- Unique MCP: **27 search + 72 read**; first edit at tool step **~111**; **~102** locate calls before first edit
- Native reads *did* drop (15 vs 189) — substitution worked on that axis; **MCP thrash** destroyed ROI

This corpus has queries, targets, payloads, and phase timing — essential for “what information must be fed when.”

### 2.3 Prior product hypotheses (reference only — not locked)

| Spec | Agent-facing idea |
|---|---|
| `2026-08-08-tracelab-three-tool-context-engine-design.md` | map / focus / workspace |
| `2026-08-08-session-native-context-engine-design.md` | + recall / expand (session store) |
| Current `CTX_MCP_SURFACE=read` | search / read / status |

These optimized for **append savings given TraceLab waste**. They did **not** fully solve “sealed primary environment in Cursor without trajectory tax.”

---

## 3. Research stance (how we will decide later)

1. **Needs before tools.** Enumerate retrieval *jobs* an agent must be able to perform. Only then invent ≤6 tools that cover the jobs.
2. **Trajectory is general, not a fixed script.** Cold start ≠ follow-up ≠ repair; already-have-context changes the entry point. The instruction describes a *grammar* of moves, not one linear path.
3. **Feed quality over call count.** Wrong question: “how many MCP calls?” Right question: “what minimum information must enter the prompt before the next reasoning/edit step?”
4. **Completeness is a constraint of sealing.** If we ban native locate, every job that used Grep/Glob/Read/ls/rg/sed must map to *some* CE tool — or we have designed a trap.
5. **Out of scope for the retrieval set:** mutate (Edit/Write), verify (pytest/npm), git write ops. Shell stays for those. Optional later: whether *read-only* git/diff belongs in the six — deferred until need evidence says yes.

---

## 4. Retrieval needs (draft taxonomy from sessions — not tools)

Derived from TraceLab WF1–WF6 + role timelines + Cursor trial conversations. Each row is a **need**; coverage of these is the later completeness checklist.

| ID | Need (agent must be able to…) | When it shows up | TraceLab signal | Cursor trial signal |
|---|---|---|---|---|
| N1 | **Orient** — know repo shape / where to stand | Cold start; after topic shift | First actions often `ls`/`pwd`/`find` | Glob cascades; early search without map |
| N2 | **Soft locate** — find “where X happens” without exact string | New feature, unfamiliar code | High `locate` share; rg/grep loops | CE `search` intended; under/over used |
| N3 | **Hard locate** — exact token / import / error string | Repair, config, symbol token | Shell `rg`/`grep` | Native Grep persists even under CE rules |
| N4 | **Name locate** — known filename / path pattern | “open handlers.py” | Glob/find | Glob |
| N5 | **Skim structure** — defs/outline without full file | Before deep read | Often full Read instead | Missing or rare (outline surface underused) |
| N6 | **Open span** — right chunk for edit/reason (not whole file) | Before mutate | Read/cat/sed; huge `result_chars` | CE `read` or native Read; v6 over-read |
| N7 | **Deepen / neighbors** — callers, callees, related wiring | Shared code, “who calls” | Graph opportunity O3≈1.0 | `neighbors=true` rare vs thrash reads |
| N8 | **Session memory** — “what did we already fetch?” | Follow-ups (195/200 multi-turn) | 21% dup signatures; near-dup reads | CE `unchanged` stubs exist; agent still re-calls |
| N9 | **Budgeted widen** — thin hits → broaden once, not forever | Search loops | Retrieval streaks ≥3 | k=10 / re-search loops; late first edit |
| N10 | **Stop collecting** — enough to mutate | After bootstrap | Late first mutate (dozens–hundreds of tools) | first_edit_step 57–111; KPI candidate |

**Canonical observed chain (TraceLab):** locate → read → mutate → verify.  
**Engine goal:** preserve that *information order*, not that *native tool order*.

### 4.1 Workflow regimes (entry points into the same need set)

From `generalized_workflows.json` / DETAILED report (prevalence approximate):

| Regime | Rough prevalence | Dominant needs |
|---|---|---|
| WF1 Cold start | ~20% | N1 → N2/N3 → N5/N6 → N10 |
| WF2 Follow-up | ~30% | N8 first, then N2/N6; avoid full N1 |
| WF3 Repair | (error-driven) | N3 + N6 in hot zone; N9 once |
| WF4 Search-heavy | mixed | N2/N3 loops — needs hard stop (N10) |
| WF5 Edit-heavy | mixed | N6/N8 only; minimal locate |
| WF6 Multi-turn re-orient | common | N8 + light N1; not cold-start dump |

A **general trajectory grammar** must support all six regimes without a separate playbook doc.

---

## 5. What “good context feeding” looks like (reasoning, still no tools)

Working model of information the agent needs across time:

```text
t0  User ask
t1  Orientation signal (small): where in the repo this task lives
t2  Candidate pointers (medium): ranked files/spans + why
t3  Decision span(s) (bounded): code actually used for reasoning/edit
t4  Optional graph glue (small): callers/callees if wiring matters
t5  Edit / verify  (out of retrieval set)
t6  On follow-up: memory first → only fetch delta
```

**Wrong feed patterns (evidence-backed):**

1. **Dump-then-think** — large unused results (5,537 events in TraceLab).
2. **Re-pay** — duplicate signatures / near-dup reads (dominant multi-turn tax).
3. **Infinite locate** — search/read streaks with no mutate (Cursor +93%: 102 locate before edit).
4. **Trajectory collision** — two locate systems (native + MCP) competing → either under-use or double tax.

**Right feed patterns (hypotheses to validate):**

1. Pointers before bodies.
2. One deepen per decision, then mutate.
3. Session-local identity for spans (handles) so re-need ≠ re-dump.
4. Escape hatch only when the retrieval environment returns hard failure / empty after honest try — not when the agent is merely impatient.

---

## 6. Open research questions (must answer before tool design)

### Completeness

1. For each need N1–N10, what is the **minimum** capability an agent requires so it never *must* leave the sealed set?
2. Which needs are **frequent but cheap** (must have a tool) vs **rare** (fold into another tool’s mode)?
3. Does “exact string” (N3) belong inside the sealed set? (Prior CE dropped MCP grep because it only rerouted native — under *soft* insert. Under *seal*, the answer may flip.)

### Trajectory

4. What is a **general move grammar** (≤300 tokens) that covers WF1–WF6 without encoding one linear script?
5. How does the agent know **entry state** (cold vs hot vs repair) without a doc? (Tool results hints? `status`/`workspace` card?)
6. What metrics detect **thrash** early (unique retrieval calls, first_edit_step, locate streak) so product + eval can reject bad instruction drafts?

### Evidence gaps

7. TraceLab lacks queries/paths — do we need a **Cursor-native corpus** (more SDK trials + optional user sessions) to label needs N1–N10 at call level?
8. How often is first retrieval **direct Read** vs **search** vs **orient** in Cursor (not just TraceLab)? That drives whether “always search first” is wrong.
9. After MCP `unchanged` stubs, why do agents still re-call? Instruction? UX? Missing `recall`?

### Success definition (for later A/B)

10. Primary KPIs when sealed: task success (same rubric), work_tokens ≤ raw, wall time, **and** retrieval thrash guards (`unique_retrieval`, `first_edit_step`, native_locate≈0 except documented MCP failure).

---

## 7. Research plan (execute before deciding tools)

### Phase R0 — Freeze scope (this week)

- [x] Problem + thesis written (this doc)
- [ ] Confirm seal rule: MCP-only locate unless MCP hard-fails
- [ ] Confirm out-of-scope: mutate + verify stay native

### Phase R1 — Need coverage matrix from TraceLab (structural) ✅

**Deliverable:** `research/tracelab/reports/retrieval_need_coverage.md` (+ `.json`; script `research/tracelab/scripts/phase_r1_r2_need_coverage.py`)

**Headline (200 sessions, 71,727 labeled retrieval calls):** N6 span-open **64%**; N3 hard-locate proxy **18.5%**; N1 orient **8.2%**; N2 under-identified (sanitized). Every session has retrieval loops; p50 **27** tools before first mutate; **197/200** sessions show duplicate locate/read signatures.

### Phase R2 — Semantic labeling from Cursor trials ✅

**Deliverable:** `research/tracelab/reports/cursor_retrieval_need_labels.md` (+ `.json`)  
**Reconcile:** `research/tracelab/reports/retrieval_need_reconcile_r1_r2.md`

**Headline (16 arms / 8 runs):** N6 **56.5%**, N3 **27%**, N4 **5.9%**, N2 **4.5%** (CE only); N5=0; N7 rare. Thrash (`20260810T145505Z` ce_read): N2×25 + N6×74, first_edit **111**. Efficient CE v5: N2×7 + N6×36, first_edit **57**.

### Phase R3 — Information diet study ✅

**Deliverable:** `research/tracelab/reports/retrieval_information_diet_r3.md` (+ `.json`; script `phase_r3_information_diet.py`)

**Headline:** Thrash vs efficient CE have **similar unique pre-edit chars** (~150–170k) but thrash uses **~2× pre-locate calls** and first_edit **111 vs 57**. Edit-touching floor only **~10–37k** chars. Work-token blowup = round-trip / N10 failure, not missing information capacity.

### Phase R4 — Completeness stress test (paper design) ✅

**Deliverable:** `docs/superpowers/specs/2026-08-10-retrieval-seal-completeness-r4.md`  
(+ `research/tracelab/reports/retrieval_seal_gaps_r4.json`)

**Headline:** Under seal, current `search/read/status` **fails** — missing N3 exact, N4 files, N1 orient, N8 recall. CE arms still do 50–80 native locate calls. **Approved** baseline: **`search | files | read | recall | expand | status`**.

### Phase R5 — Instruction grammar draft (&lt;300 tok) ✅ (draft in design)

**Deliverable:** `SERVER_INSTRUCTIONS_NAV` text in `2026-08-10-sealed-retrieval-nav-design.md` §4.  
**Implementation:** `docs/superpowers/plans/2026-08-10-sealed-retrieval-nav.md` (not started until user says implement).

---

## 8. Decisions locked (2026-08-10)

| Topic | Decision |
|---|---|
| Tool count / names | 6: `search`, `files`, `read`, `recall`, `expand`, `status` |
| Exact locate | Inside seal via `search(mode=exact)` |
| Outline / neighbors | Modes on `read(detail=…)` |
| Glob / Grep / native Read under sealed trial | Banned except MCP hard-fail |
| Rollout | Trial surface `nav` first; keep soft `read` surface for default Cursor |

---

## 9. Immediate next step

`nav` surface + sealed harness **implemented** (plan Tasks 1–6 unit-complete). Optional paid rematch:

```bash
.venv\Scripts\python.exe scripts\experiments\sdk_mcp_dev_trial.py --prompt-id combo --arms ce_nav,raw --surface nav --seal-locate --model default
```

---

## 10. References

- `research/tracelab/reports/DETAILED_AGENT_WORKFLOWS.md`
- `research/tracelab/processed/cross/session_savings_levers.json`
- `research/tracelab/processed/cross/generalized_workflows.json`
- `docs/superpowers/specs/2026-08-08-tracelab-context-collection-research-framework.md`
- `docs/superpowers/specs/2026-08-08-tracelab-three-tool-context-engine-design.md`
- `docs/superpowers/specs/2026-08-08-session-native-context-engine-design.md`
- `docs/superpowers/specs/2026-08-10-sealed-retrieval-nav-design.md`
- `docs/superpowers/plans/2026-08-10-sealed-retrieval-nav.md`
- Trial note: CE v6 default rematch `20260810T145505Z` (+93% work tokens; MCP thrash)
