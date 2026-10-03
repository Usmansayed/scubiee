# Old vs New Scubiee: mini_v3 (single-tool map) vs map_v3/U (4-config)

Both bridges deep-verified + preflit (P25): same warm/dense engine, sync-correct, all gates green,
both live-usable. Test: 16 cells (12 retrieval + 4 dev), n=2. OLD = mini_v3 (returns location cards
only, agent reads bodies natively). NEW = map_v3 with the U prompt (configs return bodies+wiring).

## Results (tokens | grep | native-read | recall/oracle)

| task | type | OLD mini_v3 | NEW map_v3/U |
|---|---|---|---|
| faiss_reimport | focused | 146k/178k \| 0,1 \| 1,1 \| rec 1.0 | **122k/156k \| 0,0 \| 0,0 \| rec 1.0** |
| memory_budget | cross_module | 229k/275k \| 1,1 \| **4,5** \| rec 1.0 | **163k/287k \| 0,2 \| 0,1 \| rec 1.0** |
| first_map_skips | discovery (hard) | 554k/564k \| 8,6 \| rec **0.0/0.0** | 655k/568k \| 9,10 \| rec **0.0/0.0** |
| dirty_files_cap | dev edit | **505k/148k** \| 6,0 \| oracle 1.0 | **154k/159k** \| 0,2 \| oracle 1.0 |

## Per-type verdict
- **Focused (faiss): NEW wins** - cheaper (122k/156k vs 146k/178k), 0 native reads (bodies inline) vs
  old's 1 read each. Both correct.
- **Cross_module (memory): NEW wins the structural point** - old needed 4-5 NATIVE READS to see the
  bodies its pointer-only map located; new needed ~0 (bodies returned inline). Both correct; new
  cheaper on r1 (163k vs 229k), ~tied on the noisy r2.
- **Dev edit (dirty_files): NEW wins decisively on CONSISTENCY** - new 154k/159k (both tight) vs old
  505k/148k (one catastrophic 6-grep spiral). New mean 156k vs old 327k = NEW ~52% cheaper. The old
  pointer-only map left the agent to grep-chain its way to the edit; new's inline bodies kept it
  decisive. Both correct.
- **Discovery (first_map): TIE at failure** - BOTH recall 0.0 both reps. This is the known
  behavioral-concept TOOL-recall gap: code doesn't lexically match the query, so neither
  pointer-map+grep (old) nor find/graph (new) locates it. Not an old-vs-new differentiator.

## Overall verdict: NEW (map_v3/U) is better
On every SOLVABLE task type (focused, cross_module, dev edit) the new 4-config map is cheaper and/or
more consistent than the old single-tool map, at equal correctness. The core structural reason: the
old map returns only LOCATIONS, forcing the agent into native Reads (cross_module: 4-5 reads) and
grep-chains (dev edit: a 6-grep 505k spiral); the new map returns the CODE + WIRING inline, so the
agent acts in fewer calls. Discovery is a tie-at-failure (a tool-recall gap neither solves).

Net token means over the 16 cells (ex-discovery, the shared failure): NEW clearly lower, driven by
eliminating old's native-read / grep-chain tails. NEW also never had old's 505k catastrophic cell.

## Caveats
- n=2; directional. Discovery remains an engine-recall shortcoming for both (log: needs better
  semantic recall on behavioral concepts).
- One noisy new cross_module r2 (287k, 2 grep) - new isn't perfectly tight either, but it never had
  old's catastrophic tail.
- This is OLD-vs-NEW (both WITH Scubiee). The with/without-Scubiee round (Scubiee vs native-only) is
  the next, separate test.
