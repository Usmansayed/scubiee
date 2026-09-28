# One MCP outcome scenario

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One live scenario, driven through `scubiee-mcp-bridge` `tools/call`, that fails when the JSON an agent reads is wrong.

**Architecture:** Copy `tests/fixtures/mcp_outcome_repo` to a temp dir, index it, attach `BridgeHost` (`packages/pipeline/mcp_host_sim/hosts/bridge_stdio.py`) the way Cursor does. Run the acts below in one session. Score only parsed tool JSON. No monkeypatches, no spies, no engine-name asserts.

**Tech Stack:** pytest marker `mcp_outcome`, `BridgeHost.call_tool`, `scubiee index` on the fixture only.

**Spec:** Realistic MCP/CLI or host-sim outcomes, not scripted unit stand-ins.

## Global Constraints

- Pass/fail comes from tool JSON fields an agent uses: `suggested_seed`, `cards`, `heatmap[].heat`, `heatmap[].s` or `symbol`, `loc`, `thin`, and body text when bodies were requested.
- Do not assert `engine`, `elapsed_ms`, call counts, `__file__`, or exact neighbor paths.
- Requested seeds may trade places with each other. A non-seed before a requested seed fails.
- `thin: true` passes if the seeds are still the front hot rows.
- Retry `ast_warming` / `dense_embed_loading` up to 3 times. Anything else fails.
- Do not run this against the full context-engine index.

## The scenario

Fixture files:

| File | Symbol | Why it is there |
|---|---|---|
| `pkg/beacon.py` | `outcome_beacon_zulu` | primary seed; body contains `OUTCOME_ZULU_9917` |
| `pkg/beacon.py` | `outcome_helper_yankee` | second seed, same file |
| `pkg/trace_api.py` | `rank_outcome_cards` | third seed, different module, no callers |
| `pkg/distractor.py` | `keeper_tick_like` | stuffed with sync/map/pack/index words so a bad ranker prefers it |
| `pkg/other.py` | `unrelated_alpha` | target of a second map, to prove the session did not stick |

Acts, in order, same bridge session:

1. **gate** — response text contains `1:ce_`.
2. **map distractor** — query is only the distractor vocabulary (`keeper_tick_like sync map pack index`). Top card file is `pkg/distractor.py`.
3. **map beacon** — query names `outcome_beacon_zulu` and `OUTCOME_ZULU_9917`. `suggested_seed.symbol` is `outcome_beacon_zulu` and `cards[0].file` is `pkg/beacon.py`.
4. **pack three seeds** — `seed_*` beacon, `seed2_*` yankee, `seed3_*` `rank_outcome_cards`, `mode=lean`. The first rows of `heatmap` are those three symbols, all `heat=hot`. `pkg/distractor.py` is not ahead of them. This is the incident: map-reuse of act 2 used to win.
5. **expand_context** — `node` is the pack seed id from act 4. After warming retries, `ok` is true and the payload mentions `outcome_beacon_zulu`.
6. **collect_hot_context** — `ids` are the three seed ids from act 4. Each returned body contains that symbol. No body is `keeper_tick_like`.
7. **edit** — change the beacon return string to `OUTCOME_ZULU_9917_V2`, mark the file dirty the way a save does, wait up to 60s.
8. **map edited token** — query contains `OUTCOME_ZULU_9917_V2`. Top card file is `pkg/beacon.py` and its `why` text contains `V2`.
9. **map other** — query names `unrelated_alpha`. Top card file is `pkg/other.py`, not `pkg/beacon.py`.
10. **pack bodies** — same three seeds, `include_bodies=1`. Response text for the beacon contains `OUTCOME_ZULU_9917_V2`.

Stop at the first failed act. The failure message is the act name plus the top 5 heatmap or card rows (rank, heat, file, symbol). No engine field.

## Why this set, and nothing wider

These ten acts are the ship ladder an agent actually walks, plus the two bugs already observed (seed demoted under the previous map, edit invisible until sync). Each act deletes a class of wrong answer:

| Act | Bug it fails on |
|---|---|
| 2 then 4 | Pack replays the previous map and buries the seed |
| 3 | Map misses an exact symbol that is in the index |
| 5 | Expand does not accept the id pack just returned |
| 6 | Collect returns a different file than the ids asked for |
| 8 | Edit never reaches map |
| 9 | Session cache ignores the new query |
| 10 | Bodies flag is ignored or returns the pre-edit text |

Latency, keepalive, and idle unload stay on Lane A host-sim. Putting time budgets in this scenario makes a slow machine look like a bad ranker.

## Tasks

### Task 1: Fixture and recorded-JSON scorer

**Files:** `tests/fixtures/mcp_outcome_repo/**`, `tests/mcp_outcome_score.py`, `tests/test_mcp_outcome_score.py`

- [ ] Add the fixture files above.
- [ ] `pack_seeds_front(payload, symbols)` and `map_top(payload, file, symbol, text_has)`.
- [ ] Recorded incident JSON (seed cold, distractor hot at rank 1) makes `pack_seeds_front` false. A correct three-seed payload makes it true.
- [ ] Run: `python -m pytest tests/test_mcp_outcome_score.py -q`

### Task 2: Live scenario

**Files:** `tests/test_mcp_outcome_live.py`

- [ ] Marker `mcp_outcome`. Skip only if `SCUBIEE_SKIP_MCP_OUTCOME=1`.
- [ ] Temp copy, `scubiee index --force`, `BridgeHost` against that repo.
- [ ] Run acts 1–10. Use the installed bridge binary, not an in-process `create_mcp` import, so a stale uv copy fails here.
- [ ] Run: `python -m pytest tests/test_mcp_outcome_live.py -q -m mcp_outcome --tb=short`

### Task 3: Pre-prod

- [ ] Call this test from the same pre-prod entry that runs Lane A. Red outcome fails the battery even when Lane A is green.

## Done when

- The incident heatmap fails the scorer.
- A warm run of acts 1–10 passes on the fixture.
- `tests/test_mcp_outcome_live.py` does not patch `pipeline`.
