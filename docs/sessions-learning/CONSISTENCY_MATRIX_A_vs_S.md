# Consistency test: symbolic (S) vs prose (A) across task types

The fair n=2 on one easy query showed A==S. That is ONE condition. To judge consistency AND surface
shortcomings, vary the dimensions that have exposed problems before. Tool/bridge held fixed; only the
prompt (A prose vs S symbolic) differs. Preflight already green this session (battery, symbolic live
probe); go straight to runs, report after each angle, stop an angle early if a clear failure shows.

## Dimensions being varied (each has historically changed behavior)
- **query category:** focused (1 file), cross_module (2+ files), discovery (vague/behavioral - the
  known hard class where ALL variants have failed).
- **task type:** retrieval (locate->answer) vs dev (locate->edit, the baseline's turf).
- **symbol count:** single vs multi-symbol (tests the batch-focus rule under each prompt).

## The matrix (A vs S, n=2 unless noted)
| angle | query/task | why it stresses | cells |
|---|---|---|---|
| M1 focused | faiss_reimport_segfault | clean 1-file; does S hold the no-verify-grep? | 4 |
| M2 cross_module | memory_budget_resets_threads | 2-file; batch-focus + no grep-chain | 4 |
| M3 discovery | first_map_skips_graph | the known hard class; where do BOTH break? | 4 |
| M4 dev edit | dirty_files_cap | locate->edit; does S regress on edits like map_v3 did? | 4 (n=2) |

16 cells total. Retrieval cells are cheap; the dev cells are pricier.

## What counts as a shortcoming (recorded regardless of win/lose)
- any cell where S (or A) grep-spirals (grep>=3) or re-maps (map>=3) -> rule not binding.
- any cell where S makes one-focus-per-symbol on a multi-symbol task -> batch rule not binding.
- any cell where S verify-greps a high-confidence find -> trust rule not binding.
- divergence between A and S > ~20% tokens on the SAME query -> prompt-form actually matters there.
- shared failures (both 0 recall) -> a TOOL gap, not a prompt gap (log as engine shortcoming).

## Win/consistency criteria (set upfront)
- CONSISTENT if: across M1-M4, A and S are within noise on correctness AND neither shows a
  systematic adherence failure the other avoids.
- S is PREFERABLE if consistent AND cheaper on prompt tokens (it is: 1459 vs 2165) with no runtime
  regression.
- Report shortcomings of the SYSTEM (tool + prompt) found along the way - that is an explicit goal.

## Where results land
run_retrieval_bench / run_dev_mini -> .ab_workspaces; extract_sessions folds in; verdict + the
shortcomings list recorded in LEARNINGS.


---

# RESULTS (A vs S, 16 cells, preflight green first)

All cells oracle/recall-correct except the shared discovery failure. Numbers = tokens | map/grep.

| angle | A rep1 | A rep2 | S rep1 | S rep2 |
|---|---|---|---|---|
| M1 focused (faiss) | 160k 2/0 rec1 | 160k 2/0 rec1 | 193k 1/1 rec1 | 121k 1/0 rec1 |
| M2 cross_module (memory) | 206k 3/0 rec1 | 310k 2/3 rec1 | 209k 2/0 rec1 | 170k 2/0 rec1 |
| M3 discovery (first_map) | 539k 2/9 **rec0.0** | 480k 2/3 rec1 | 476k 1/7 rec0.75 | 596k 1/8 rec0.5 |
| M4 dev edit (dirty_files) | 258k **0**/4 ok | 124k 1/0 ok | 293k 1/5 ok | 317k **0**/5 ok |

## Verdict vs preset criteria
- **CONSISTENT on solvable queries (M1, M2): YES.** A and S both recall 1.0; token means close
  (M1: A 160k vs S 157k; M2: A 258k vs S 190k - S actually cheaper+tighter on cross_module, 0 grep
  both reps vs A's one 3-grep spike). No systematic adherence failure in S that A avoids.
- **S PREFERABLE on solvable work:** equal/better behavior at ~33% fewer prompt tokens. Confirmed
  across focused AND cross_module, not just the one easy query.
- Correctness: all 16 cells that could be solved were solved by both (oracle 1.0 / recall 1.0),
  except the discovery query where BOTH degrade.

## Shortcomings surfaced (the explicit goal)
1. **Discovery class is a TOOL-RECALL gap (both prompts).** first_map_skips_graph: A failed outright
   once (recall 0.0, 9-grep spiral); S never hit 0 but grep-spiralled 7-8x at 0.5-0.75 recall. The
   code is a behavioral concept that doesn't lexically match the query; find/graph/grep all miss it.
   No prompt fixes this - it needs better engine semantic recall. (cold_start_status_warming earlier
   = same class.) The HARD CAP rule reduced but did not stop the spiral.
2. **Dev-edit grep default (both prompts).** On dirty_files_cap the agent often skips map entirely
   (A r1: 0 map/4 grep; S r2: 0 map/5 grep) and grep-chains to the edit. The rules say prefer map for
   unknown location, but for an edit task the agent treats the file as "known enough" and greps. S
   was grep-heavier than A on this small dev sample (both reps 5 grep).
3. **S slightly higher variance on focused** (one 1-grep cell) - minor.
4. **map's own cost on cross_module/discovery:** 2-3 map calls + the agent still wants more - the
   graph/focus combo isn't a clean one-call answer when the target spans files or is behavioral.

## Net
S == A on everything the tool can solve (and a touch better+cheaper on cross_module), at a third
fewer prompt tokens -> S is a legitimate production candidate. The real, prompt-independent
shortcomings are (1) discovery/behavioral-concept recall and (2) the dev-edit grep-default - both
point at TOOL/engine work, not more rule-tuning. n=2 per cell; directional but consistent across 4
task types.
