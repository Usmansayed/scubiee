# Scubiee Token Benchmarks

Scubiee saves coding agents **30%+ of their tokens on average**.

These are measured A/B results, not estimates. Each test runs the same agent on the same task
twice: once **with Scubiee** and once **without** (native search tools only). Every run is graded
by hidden tests the agent never sees.

## Summary

| Agent | What we measured | Without Scubiee | With Scubiee | Saved |
|---|---|---:|---:|---:|
| Claude Code | All multi-file dev tasks (9 tasks, 67 runs) | 730,980 tokens | **287,629 tokens** | **61%** |
| Claude Code | Hard cross-module changes (5 tasks, 34 runs) | 939,252 tokens | **316,681 tokens** | **66%** |
| Claude Code | Simpler single-file changes (4 tasks, 33 runs) | 544,631 tokens | **252,351 tokens** | **54%** |
| Kiro CLI | Three dev tasks (22 runs) | 6.42 credits avg | **2.65 credits avg** | **54%** avg per task |

**Across every individual task we measured (11 tasks, including one where Scubiee cost slightly
more), the median saving is 32% and the mean is 39%.**

Details: [Claude Code results](claude-code.md) · [Kiro CLI results](kiro.md) ·
[raw numbers (JSON)](benchmarks.json)

## Highlights

| | Without Scubiee | With Scubiee |
|---|---:|---:|
| Hardest single task (Claude Code) | 2,596,365 tokens | **435,092 tokens** (83% saved) |
| Best Kiro task (integration) | 4.31 credits | **1.08 credits** (4x cheaper) |
| Tool calls per hard task | 18.4 | **9.5** |
| Grep searches per hard task | 7.2 | **1.3** |
| File reads per hard task | 6.6 | **2.6** |
| Long feature build on Kiro, wall time | ~310 s | **~205 s** (35% faster) |

## Where the savings come from

- **The harder the code is to find, the bigger the saving.** Easy, exact-name edits save 10–20%;
  hard cross-module changes save 50–80%.
- **Fewer wasted searches.** Without Scubiee, agents search, read the wrong file, and search again.
  Scubiee hands back the right code and its callers in one or two calls.
- **No runaway sessions.** Without Scubiee, one agent run passed 2.1M tokens on a single task.
  Scubiee's worst run on the same task was about 578k.

## Methodology

- **Same everything except Scubiee.** Both arms get the same prompt, model, permissions and
  starting code (byte-identical git snapshots). The only difference is the Scubiee MCP server and
  its rules.
- **Hidden tests grade every run.** Each task has a deterministic test suite the agent never sees.
  Tests were checked to fail on the original code and pass on a correct change.
- **Real token accounting.** Claude Code numbers are the Claude Agent SDK's per-model usage
  (input + output + cache reads + cache writes). Kiro numbers are Kiro's billed credits.
- **Locate-and-edit only (Claude Code).** Shell access was disabled in both arms.
- **Cost cap.** Each Claude Code run was capped at $4. This cut off the worst no-Scubiee runs, so
  the real gap is **larger** than shown.
- **Real tasks.** Every task is a real change to a 130+ module Python codebase, not a toy example.

## Limits

- Internal benchmarks on one codebase, not a third-party evaluation.
- 2–5 runs per task per arm. Agent cost varies run to run; the direction is consistent across
  tasks, individual percentages are not tight estimates.
- On trivial edits where the target is an exact, searchable name, the saving is small or zero.
- Kiro credits and Claude Code tokens are different units; don't compare them with each other.
