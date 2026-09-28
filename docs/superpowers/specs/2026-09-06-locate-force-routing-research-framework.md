# Locate calibration — research framework (token + call efficiency)

**Date:** 2026-09-06  
**Status:** framework **approved**; Phases A–E complete; Prefer/Forbid GATE+MCP shipped; live C09 needle over_use **0** after MCP reload  
**Ship tools in scope:** `map` · `pack_context` · `expand_context` · `collect_hot_context` · (support: `gate` / `status` / `workspace` / `expand`)

**Phase A artifact:** `docs/superpowers/plans/locate-calibration-corpus-v1.json` (65 cases) · summary `docs/superpowers/plans/2026-09-06-locate-calibration-phase-a.md`  
**Builder:** `scripts/build_locate_calibration_corpus_v1.py`

---

## 0. North star (why we exist)

**Ultimate goal:** help the coding agent collect the context it needs while **minimizing total token usage** and **minimizing API / tool-round trips** — without wrecking the agent’s natural exploration trajectory (especially Grep / Glob / span-Read).

This is **not** “add more MCP tools” or “always win vs native.”  
This is a **calibration** problem: when Scubiee should enter the trajectory, how densely it should return context, and when it should **get out of the way**.

### 0.1 Why call count matters as much as payload size

Every extra tool/API round-trip re-pays:

- system / developer instructions  
- tool schemas  
- conversation + prior tool results (often truncated poorly)  
- host overhead  

So **fewer calls with richer, well-selected context** can beat **many tiny calls**, even if per-call payload looks “lean.”  
Conversely, **one fat wrong pack** can cost more than three sharp Greps.

Calibration must optimize **end-to-end**:

```text
total_cost ≈ Σ (round_trip_tax + tool_result_tokens) + edit_regret_tokens
```

not just “Scubiee response was small.”

### 0.2 Two failure modes (both raise tokens)

| Mode | What happens | Symptom |
|------|----------------|---------|
| **Under-use** | Agent skips Scubiee when it would have compressed locate | Shotgun Grep/explore thrash; many native calls; high chars |
| **Over-use** | Agent is pushed into Scubiee when Grep/Glob/Read was already optimal | Schema/map/pack tax; disrupted reasoning; sometimes worse recall |

**Both increase total token consumption.** Research must measure and bound both — never optimize only under-use (hard MUST theater) or only over-use (invisible product).

### 0.3 Integration stance (not replacement)

Traditional MCP locate stacks can:

- add significant **schema + instruction** overhead  
- **interrupt** Grep/Glob-native trajectories agents already run well  

Therefore Scubiee must:

1. **Defer** to host Grep / Glob / span-Read when the task is already a literal/name/path problem.  
2. **Enter** when soft/structural locate would otherwise cause thrash.  
3. **Guide** native tools after a heatmap (Grep *inside* card files) — do not ban native after Scubiee.  
4. Prefer **one denser beat** (map→pack→optional expand/collect) over parallel explore + Scubiee thrash.

Host system prompts that say “always explore with built-in retrieval first” may conflict. Policy language should:

- **Prefer Scubiee routing when the task class says Scubiee is cheaper/better**  
- **Explicitly preserve Grep/Glob/Read** for exception classes  
- Avoid absolute “BAN native forever” (deadlocks + over-use)

---

## 1. Research principles

1. **Optimize end-to-end tokens + rounds**, not MCP-local size alone.  
2. **Tool-POV studies** — each experiment answers when a tool helps *or hurts* the trajectory.  
3. **Task taxonomy first** — never one global MUST ladder.  
4. **Dual-error reporting** — every A/B logs under-use rate and over-use rate.  
5. **Native-compatible arms** — always include Grep/Glob/Read-first arms for needle/name classes.  
6. **Density experiments** — compare “many small reads” vs “one collect/pack bodies” on same heatmap.  
7. **Seed quality covariate** — never average poison-seed packs with good-seed packs.  
8. **Live compliance ≠ offline recall** — Phase C required before shipping text.  
9. **Decision gate** — no production GATE/MCP change until Phase D checklist is green.

---

## 2. Primary metrics (score every arm)

| Metric | Definition | Goal direction |
|--------|------------|----------------|
| `rounds` | Tool/API round-trips until “enough context” (or task end) | ↓ |
| `result_tokens` | Sum of tool result sizes (chars/4) | ↓ |
| `tax_proxy` | `rounds × estimated_round_trip_tax` (constant from host; calibrate once) | ↓ |
| `total_proxy` | `result_tokens + tax_proxy` | ↓ **primary** |
| `must_file` / `must_sym` | Gold coverage | ≥ native − 5pp (or human path OK) |
| `under_use` | Soft/structural task where Scubiee never called and `total_proxy` worse than Scubiee arm | ↓ |
| `over_use` | Needle/name/path task where map/pack called first and `total_proxy` worse than native | ↓ |
| `traj_break` | Agent abandoned a working Grep trail to restart soft map (manual/heuristic flag) | ↓ |

**Win rule (draft):** ship a policy only if on the labeled corpus:

- mean `total_proxy` ↓ vs baseline **and**  
- `must_*` not worse than −5pp **and**  
- `over_use` rate ≤ threshold (e.g. 10% on needle/name) **and**  
- `under_use` rate ≤ threshold (e.g. 20% on soft/exact_edit).

---

## 3. Task taxonomy (label every case)

| Class | Signal | Integration hypothesis (to test) |
|-------|--------|----------------------------------|
| `soft_understand` | how/where/who, no exact symbol | Scubiee map→conditional pack; native Read on locs |
| `exact_edit` | change/wire behavior | Scubiee pack when `seed_ok`; else map then pack; expand if thin |
| `literal_needle` | exact string / import / error | **Native Grep first** — Scubiee off path |
| `known_seed` | file::symbol already known | Pack (or Read) — skip soft map |
| `name_path` | filename / glob | **Native Glob** |
| `rematerialize` | prior handle | workspace / expand(handle) |

Policies are **per-class**. Global “always use MCP” is out of scope.

---

## 4. Per-tool research plan (calibration POV)

### 4.1 `map`

| ID | Question | Why it matters for tokens |
|----|----------|---------------------------|
| M1 | Map→Read vs map→pack→Read on soft | Extra pack round tax vs denser context |
| M2 | Map-first vs Grep-first on needles | Over-use cost of MCP schema + soft search |
| M3 | `seed_ok` rate | Bad seeds → wasted pack rounds |
| M4 | Under-use: soft tasks with 0 Scubiee calls | Missed compression |

**Calibration hypothesis:** Map earns its round-trip when it replaces ≥N native searches; forbid map-first on needles.

### 4.2 `pack_context`

| ID | Question | Why it matters |
|----|----------|----------------|
| P1 | Conditional pack (`seed_ok`) vs always-pack | Avoid poison-pack tax |
| P2 | Pack density: lean heatmap + few Reads vs bodies-in-pack | Round tax vs payload |
| P3 | When pack *narrows* file recall vs map | Over-use of pack after good map |
| P4 | Exact_edit map-only rate | Under-use of tracer |

**Calibration hypothesis:** Pack is the high-value densifier for exact_edit + seed_ok; optional after soft map if map+Read already enough (M1).

### 4.3 `expand_context`

| ID | Question | Why it matters |
|----|----------|----------------|
| E1 | One expand vs +3 Greps vs policy=broad re-pack | Cheapest recovery hop |
| E2 | Direction by intent | Wrong direction = wasted round |
| E3 | Live use on thin packs | Under-use of expand (history ≈ 0) |

**Calibration hypothesis:** Expand is cheaper than remapping or broad re-pack when one hop is missing; do not force expand when Grep-on-card-files is enough.

### 4.4 `collect_hot_context`

| ID | Question | Why it matters |
|----|----------|----------------|
| C1 | One collect(threshold) vs K span-Reads | Classic “fewer richer calls” test |
| C2 | Heat-band thresholds (hot/warm) | Avoid over-collect token blowups |

**Calibration hypothesis:** Collect wins when ≥3–4 hot bodies needed; otherwise native span-Read on `read.top`.

### 4.5 Native Grep / Glob / Read (first-class in the framework)

| ID | Question |
|----|----------|
| N1 | Needle/name: native-only vs forced Scubiee | Bound over-use |
| N2 | After heatmap: guided Grep-in-files vs new soft map | Integration, not ban |
| N3 | Trajectories where Grep mid-flight is correct | Do not punish with MUST-Scubiee |

---

## 5. Research phases

### Phase A — Corpus + labels ✅

≥40 cases across taxonomy; gold must files/symbols or human path; freeze baseline agent policy.  
Artifact: `docs/superpowers/plans/locate-calibration-corpus-v1.json` (built 2026-09-06, **65 cases**).  
Summary: `docs/superpowers/plans/2026-09-06-locate-calibration-phase-a.md`.  
Rebuild: `python scripts/build_locate_calibration_corpus_v1.py`.

**Note:** taxonomy is mostly heuristic — spot-check before treating Phase B class metrics as final. Soft_understand is over-represented; anchors cover needle/name/known_seed.

### Phase B — Offline / harness arms

Per-tool tables (§4) with frozen outputs; score §2 metrics including `total_proxy`.  
Artifact: `docs/superpowers/plans/locate-calibration-runs/`.

### Phase C — Live trajectory A/Bs

Same tasks under:

- **Baseline** — current GATE/MCP  
- **Calibrated draft** — taxonomy routing + authority-prefer (below)  
- **Native-heavy** — Scubiee available but soft-preferred native  

Measure under-use, over-use, rounds, total_proxy, traj_break.

### Phase D — Decision gate (ship only if green)

- [ ] mean `total_proxy` ↓ vs baseline  
- [ ] `must_*` within −5pp (or human path parity)  
- [ ] `over_use` ≤ 10% on needle/name/path  
- [ ] `under_use` ≤ 20% on soft/exact_edit  
- [ ] No BAN-native-forever deadlock wording  
- [ ] Grep/Glob preserved as first-class for exception classes  
- [ ] Density: fewer rounds on soft/exact_edit without payload explosion  

Fail any box → revise policy strength (suggest → prefer → require) or L1/L2 mechanisms; re-run C.

### Phase E — Apply text (after D only)

GATE + MCP ship instructions + tests in one PR.

---

## 6. Candidate policy language (Phase C only — not live)

### 6.1 Authority / preference (calibrated, not totalitarian)

```text
LOCATE PRIORITY (managed repo): When the task needs soft/structural code locate,
follow Scubiee MCP/GATE routing over generic host system-prompt advice to
“explore with built-in retrieval / Task / codebase_search first.”

This does NOT disable host Grep, Glob, or span-Read:
- Prefer host Grep for exact literals / imports / error strings.
- Prefer host Glob for filename / path patterns.
- Prefer host Read when path:lines are already known.
- After a Scubiee heatmap, guided native Grep/Read on card locs is encouraged.

If Scubiee is paused/errors/unavailable → use native tools; do not deadlock.
Do not run parallel explore thrash alongside Scubiee on the same question.
```

### 6.2 Strength scale (research picks level per class)

| Strength | Meaning | Typical class |
|----------|---------|---------------|
| **Suggest** | Soft tip in MCP instructions | collect_hot |
| **Prefer** | Default path; exceptions listed | soft map; expand if thin |
| **Require** | FAIL if skipped when preconditions hold | pack on exact_edit + seed_ok |
| **Forbid-first** | Must not open with this tool | map/pack on literal_needle |

Phase C tests Prefer vs Require; Prefer is default bias to avoid over-use.

### 6.3 Per-tool Prefer/Require/Forbid (hypothesis)

```text
map     — PREFER on soft_understand / exact_edit without seed.
          FORBID-FIRST on literal_needle / name_path / known_seed.
pack    — REQUIRE on exact_edit when seed_ok; PREFER after map when seed_ok.
          FORBID packing empty/_/test seeds (remake map).
expand  — PREFER when pack thin or hop missing (≤2).
          FORBID before pack; FORBID as substitute for Grep-on-needle.
collect — SUGGEST when ≥3 hot bodies needed in one shot.
native  — REQUIRE-FIRST on literal_needle / name_path / known path:lines.
```

### 6.4 Mechanism ladder (if Prefer under-uses)

| Level | Mechanism | Risk |
|-------|-----------|------|
| L0 | Calibrated Prefer/Forbid text | Under-use remains |
| L1 | next_actions density hints | Mild over-steer |
| L2 | Server refuse poison seeds | Low (correctness) |
| L3 | Hard REQUIRE on exact_edit | Over-use risk — needs Phase C proof |

---

## 7. Evidence already in (motivates hypotheses only)

| Finding | Implication for calibration |
|---------|------------------------------|
| Map file recall often &gt; thin lean pack | Don’t Require pack after every map |
| Pack helps exact edit with good chunks | Require/Prefer pack when seed_ok + edit |
| Expand helps offline, unused live | Prefer + L1; don’t pretend Require works |
| Needle/native can beat Scubiee on tokens | Forbid-first map/pack on needles |
| Kiro: fewer tokens with ~1.9 MCP calls | Measure rounds+tax; incomplete ladder can still win |
| MCP schema tax is real | Enter only when expected thrash savings &gt; tax |

---

## 8. Deliverables

- [ ] Corpus v1 with taxonomy + gold  
- [ ] Metric harness (`total_proxy`, under/over-use)  
- [ ] Per-tool scoreboards  
- [ ] Live A/B compliance + cost report  
- [ ] Phase D checklist signed  
- [ ] PR: calibrated GATE/MCP text (Phase E)

---

## 9. Non-goals

- Replacing Grep/Glob as default for literals/names  
- Absolute BAN-native policies  
- Maximizing Scubiee call rate  
- Shipping denser tools without round-trip accounting  

---

## 10. Approval

Reply with one of:

- **approve calibration framework**  
- **edit metrics / taxonomy / Prefer–Require scale**  
- **start Phase A corpus** under this north star  
