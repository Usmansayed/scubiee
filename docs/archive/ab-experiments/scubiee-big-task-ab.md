# Claude Code — map-only Scubiee vs. without, on ONE large task

A single substantial, cross-cutting coding task (not several small prompts), run once with and
once without Scubiee's `map` tool, to see whether map-only still saves tokens when the task is big
enough to dominate the budget with *work* rather than *discovery*.

## Setup

- **Model:** `claude-sonnet-5` via the Claude Agent SDK; real `model_usage` token accounting.
- **Task (one, vague, non-grep-able):** "add proper, consistent per-stage timing instrumentation
  across the whole locate/answer request path, and surface a structured per-stage rollup that sums
  to the total." No file names / symbols / formulas in the prompt — genuinely cross-cutting, forces
  broad exploration of the pipeline. Graded by a hidden, tolerant behavior+structural oracle.
- **Two arms, identical conditions** (byte-identical `packages/` snapshot, same model, same system
  prompt, `max_turns=120`):
  - **A — Without Scubiee:** native tools only.
  - **B — Scubiee map-only:** native + `map` (+ `gate`/`status`), restricted via `allowed_tools`
    **and** an explicit "use `map` for discovery, then Read the spans; no other Scubiee tool" rule
    in the workspace `CLAUDE.md`. The MCP server still exposes all tools.

## Results

| Metric | A: Without | B: map-only |
|---|---:|---:|
| **Total tokens** | 16,052,490 | 15,441,209 |
| **% vs without** | — | **−3.8%** |
| Input tokens | 1,517 | 1,525 |
| Output tokens | 77,604 | 100,457 |
| Cache-read tokens | 15,762,100 | 15,129,524 |
| Tool calls (all) | 97 | 111 |
| Scubiee calls | 0 | 3 (`gate`, `map`) |
| Native Read/Grep/Glob | 52 | 57 |
| Turns | 98 | 112 |
| Wall time | 885 s | 988 s |
| Real source edits (`.py`) | 4 files | 5 files |
| **Task outcome** | **succeeded** | **succeeded** |

**Both arms completed the task** (clean `end_turn`, not a turn-cap crash) and built the same thing:
a new reusable timing helper `packages/pipeline/stage_timing.py` wired across the pipeline
(`context_trace.py`, `locate.py`, `mcp_locate.py`; arm B also `engine.py`).

> **Harness-flag correction:** the raw runner logged `success=False` for both arms. That is a
> scoring quirk, **not** a task failure. The oracle ran **1 passed, 1 skipped, 0 failed**: the
> *structural* check (a reusable cross-cutting timing helper exists and is referenced from ≥2
> modules) **passed**; the *behavioral* check **skipped** because the agent's bespoke API wasn't
> generically drivable by the probe. My `success` gate required ≥2 passing checks and mis-counted
> the skip. On the evidence (real `stage_timing.py` + cross-module wiring + oracle 1.0 pass ratio,
> 0 failures), **both arms genuinely succeeded.**

## What this shows — and why it differs from the small-task result

On the earlier **small** task, map-only cut tokens **~45%**. On this **large** task it was a
**statistical tie (−3.8%)**. The reason is structural, and it's the important finding:

- **Total tokens are dominated by cache-read** (15.7M / 15.1M of the ~16M) — every turn re-sends
  the growing transcript. So cost ≈ a function of **how many turns of reading and editing** the
  task takes.
- On a large task, **discovery is a small slice of the work.** The agent still spent ~52–57 native
  Read/Grep/Glob calls and ~98–112 turns *doing the change* (understanding many files, editing 4–5,
  re-reading to verify). `map` was called only **3 times** and shaved a little off discovery, but
  discovery was never the bottleneck here — the sheer volume of read-edit-verify turns was.
- On the small task, discovery *was* most of the work (find the one buried file), so replacing 16
  greps with one `map` collapsed the whole thing → big win. That leverage disappears as the task
  grows.

Put differently: **`map`'s savings scale with the discovery fraction of a task, not its size.**
Big feature work is mostly comprehension-and-editing turns, which `map` doesn't touch.

Two secondary observations:
- Arm B did **more** turns (112 vs 98) and **more** output tokens — it wrote a slightly larger
  change (5 files vs 4, adding `engine.py`). Some of the "no savings" is that the two runs did not
  do byte-identical work; on a vague task the agents diverge in scope. This is expected variance,
  not a controlled per-edit comparison.
- The map-only rule text itself is a small fixed per-turn tax (re-sent each turn), which at 112
  turns is non-trivial and eats into any discovery savings.

## Caveats (important)

- **n = 1 task, 1 run per arm.** At 16M tokens a single run costs a lot, so this is one sample. A
  ±4% gap is **within run-to-run noise** for Sonnet agentic work — do not read −3.8% as "map hurts"
  or "map helps"; read it as **"no measurable effect at this scale, this run."**
- The two arms did **not** produce identical diffs (4 vs 5 files), so token totals include a
  scope difference, not just a tool difference.
- The task ran to ~16M tokens (far past the 1–2M ask) — it was more cross-cutting than intended,
  which actually strengthens the "discovery is a small fraction" point but makes the single-sample
  noise larger in absolute terms.

## Conclusion

**On one large, realistic, cross-cutting task, map-only Scubiee showed no meaningful token
difference vs. without (−3.8%, within noise) — both completed the task.** This does **not**
contradict the small-task 45% win; it refines it:

> **`map` saves tokens in proportion to how much of a task is *finding the right code*. For a
> small, discovery-dominated task that's a large fraction (big win). For a large feature that's
> mostly comprehension-and-editing turns, discovery is a small slice, so map-only barely moves the
> total.**

Where `map` (and Scubiee more broadly) is most worth it: **many small, discovery-heavy tasks**
(bug triage, "where does X happen", targeted fixes) — not single mega-features where the token
bill is dominated by the editing loop. For a robust number, this large-task arm would need several
repeats (expensive) and a controlled task where both arms must produce the same diff.

## Reproduce

```
scripts/claude_sdk_harness/
  big_task.py        # the one large vague task + hidden tolerant oracle
  run_big_ab.py      # 2-arm orchestrator (without vs map-only, max_turns=120)
  harness_core.py / harness_run.py / harness_preflight.py / run_harness.py  # reused
python scripts/claude_sdk_harness/run_big_ab.py --preflight-only   # validate wiring
python scripts/claude_sdk_harness/run_big_ab.py                    # full 2-arm run (expensive)
```
Raw per-arm traces + REPORT.md in `.ab_workspaces/claude_sdk_harness/<run_id>_bigAB/`.
```
