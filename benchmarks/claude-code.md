# Claude Code benchmark results

Agent: Claude Code (Claude Sonnet) driven through the Claude Agent SDK. Token counts are the
SDK's real per-model usage (input + output + cache reads + cache writes), not estimates. Both arms
use the same native tools (Read, Grep, Glob, Edit); the "with" arm also has the Scubiee MCP server.

[Back to summary](README.md)

## Totals

| Task group | Tasks | Runs (with / without) | Without Scubiee | With Scubiee | Saved |
|---|---:|---:|---:|---:|---:|
| All multi-file dev tasks | 9 | 31 / 36 | 730,980 | **287,629** | **61%** (2.54x cheaper) |
| Hard cross-module changes | 5 | 17 / 17 | 939,252 | **316,681** | **66%** (2.97x cheaper) |
| Simpler single-file changes | 4 | 14 / 19 | 544,631 | **252,351** | **54%** (2.16x cheaper) |

Token figures are average tokens per task run.

## Hard cross-module changes

Each task needs edits in two or more files in different subsystems, where the second file can only
be found by following the call graph, not by searching for one word.

| Task | Files involved | Without Scubiee | With Scubiee | Saved |
|---|---|---:|---:|---:|
| New sync-strategy tier | freshness + sync status | 2,596,365 | **435,092** | **83%** |
| Add importers alias to expand | locate + trace | 426,064 | **163,621** | **62%** |
| Unify CPU-thread budget | memory budget + embedder | 775,718 | **404,388** | **48%** |
| Net chunk delta in sync result | incremental + sync loop | 355,826 | **243,153** | **32%** |
| Consistent safety-pause check | incremental + CLI | 119,612 | **95,810** | **20%** |
| Surface dirty count in timings | freshness + engine | 305,615 | **269,546** | **12%** |

"Add importers alias to expand" was built after the first five, in a subsystem not tested
before, to check the savings reproduce on a fresh task. They did: 2.6x cheaper.

## Two-file edits on a well-defined seam

| Task | Without Scubiee | With Scubiee | Saved |
|---|---:|---:|---:|
| Root-hash fingerprint | 275,726 | **222,343** | **19%** |
| Total-changed field | 211,608 | 226,242 | -7% |

The second task's targets are exact names that a plain text search finds in one hit, so Scubiee
had nothing to add. It is included because the overall average counts it.

## How the agent works differently (hard tasks, average per task)

| | Without Scubiee | With Scubiee |
|---|---:|---:|
| Tool calls | 18.4 | **9.5** |
| Grep searches | 7.2 | **1.3** |
| File reads | 6.6 | **2.6** |
| Worst single run | 2,145,920 tokens | ~578,000 tokens |

Scubiee returns the relevant code and its callers in one call, so the agent stops grep-hunting
through files.
