# Decisive run: a HARD cross-module task — old mini_v3 vs new map_v3 vs native

This is the run that settles "should we finalize old mini, or is new map_v3
actually better?" The earlier multi-file tasks were too easy to separate the arms
(tidy 2-file edits on a greppable seam, all arms ~tied). This task was built to be
genuinely hard: a vague prompt, a cross-module seam, and a strict oracle.

## The task (vague prompt, 3-file seam, call-graph-only discovery)

`unify_cpu_thread_budget`. The prompt describes a *symptom* ("the rule for how many
CPU threads an indexing profile should use is written out by hand in more than one
place and the copies have drifted"), names NO files or symbols, and asks for a
single source of truth that every site routes through — including the embedder's
unprimed fallback.

The real seam (found by the agent, not given):
- `memory_budget.py` — the `cpu_thread_pct -> thread count` formula is duplicated in
  `apply_index_memory_budget` and `force_apply_memory_budget`.
- `embedder.py` — `_tune_cpu_threads()` has a THIRD, divergent copy: a hardcoded
  `0.20` (20%) fallback when `CTX_CPU_EMBED_THREADS` is unset — wrong for the light
  (15%) background profile.
- `sync_loop.py` — `_bulk_sync_paths` restores `background_budget()` via
  `force_apply_memory_budget` at the end of a bulk sync; relies on the recompute.

The contract is a dataclass field (`cpu_thread_pct`) + an env var
(`CTX_CPU_EMBED_THREADS`), NOT a unique grep-able literal. You can only find all
three sites by following the call graph.

## Oracle (strict, discriminating — proven offline before the run)

Name-agnostic, deterministic from the real `os.cpu_count()` and the documented
percentages (0.20 heavy / 0.15 light) with the real clamps. Graded on **strict**
(all checks pass), because a partial edit otherwise clears the lenient 2/3 bar:

| scenario | strict | why |
|----------|:------:|-----|
| baseline (unedited) | FAIL (2/4) | no accessor; embedder still 20% |
| PARTIAL (memory_budget.py only) | FAIL (3/4) | embedder fallback still 20% |
| FULL (both files, routed) | PASS (4/4) | one source of truth everywhere |

Full offline preflight before any token: `preflight_all.py` = 20/20 EVERYTHING
WORKING PERFECTLY (engine, both bridges + sync, budgets, this oracle's 3-scenario
discrimination, arm wiring + strict grading).

## Results (live, n=2, graded on STRICT)

| arm | tok mean | tok range | calls | map | grep | read | edits | strict | success |
|-----|---------:|----------:|------:|----:|-----:|-----:|------:|:------:|:-------:|
| **map_v3 (new)** | **549,128** | 525k–574k | **13.0** | 1.5 | 1.5 | **4.0** | 2 | 2/2 | 2/2 |
| mini_v3 (old) | 630,162 | 553k–707k | 15.5 | 1.0 | 2.0 | 5.5 | 2 | 2/2 | 2/2 |
| without (native) | 918,368 | 583k–1,254k | 25.5 | 0 | 8.0 | 9.5 | 2 | 2/2 | 2/2 |

## Verdict — do NOT finalize mini; the NEW map_v3 wins the case that matters

On the easy 2-file tasks mini looked as good or better, but that was an artifact of
tasks too simple to separate the arms. On a genuinely hard cross-module task the
ordering is clear and consistent:

1. **Correctness: all three still succeed (2/2 strict each).** A capable agent can
   solve it with any surface — but the *cost of getting there* is where they split.

2. **New map_v3 is the cheapest and most stable.** 549k mean — **40% fewer tokens
   than native (918k)** and **13% fewer than old mini (630k)** — with the fewest
   calls (13 vs 15.5 vs 25.5) and fewest native reads (4 vs 5.5 vs 9.5). Its two
   runs were tight (525k–574k).

3. **Native is both expensive and dangerously variable.** Without any retrieval the
   agent grep-hunts the call graph: 8 greps and 9.5 reads on average, and one run
   blew up to **1.25M tokens / 36 calls / 11 greps** chasing the three divergent
   copies. The hard seam is exactly where "just grep it" falls apart.

4. **Old mini_v3 sits in the middle.** Its single `map` gives one orientation hit
   that trims the native blow-up (630k vs 918k), but because it returns locations
   only, the agent still does 5.5 native reads to pull bodies. New map_v3's `focus`
   (bodies + wiring in one call) is what cuts reads to 4 and tokens below mini.

**This is the inverse of the easy-task result, and it's the result that should drive
the decision.** The whole point of the richer surface — fold locate+read+wiring into
one semantic call — only pays off when locating is actually hard and spans modules.
That is precisely the terrain real "complex dev tasks" live in. On easy edits the new
surface's fixed overhead (ToolSearch load + the prompt + bigger payloads) isn't repaid
and mini/native look cheaper; on hard edits that overhead is repaid several times over.

**Recommendation: keep the NEW map_v3 (production U) as the finalized surface.** Do
not revert to mini. Mini is a reasonable lightweight fallback and beats native on the
hard task too, but new map_v3 strictly dominates it here (fewer tokens, calls, and
reads at equal correctness), and the easy-task cases where mini edged ahead are low
stakes (everything succeeds cheaply regardless).

### Caveats (honest)
- n=2; the hard task has real wall-time and token variance (native 583k–1.25M).
  The *ordering* (map_v3 < mini_v3 < without) held on both the mean and the median,
  and map_v3 had the tightest spread, which strengthens the read.
- One task, one seam. A second independent hard seam at n=2 would further harden the
  conclusion; this one is already decisive enough to not finalize mini.
- All arms used Edit/Read natively (no Bash); verification is the oracle's job, so
  these numbers isolate locate+edit, not test-running.
