# Scubiee docs

**Current version: 0.3.144** · Local AI code-context engine + MCP server ·
Windows (DirectML GPU), macOS (MLX/Metal), CPU fallback.

This index points at the **current, authoritative** docs. Historical material
(dated handoffs, A/B experiments, superseded bug reports, old research) lives
under [`archive/`](#archive) — kept for history, not current truth. If a doc and
the code ever disagree, the code wins.

---

## Start here

| If you want to… | Read |
|---|---|
| Understand what Scubiee is and how it's built | [`scubiee-overview.md`](scubiee-overview.md) |
| Use the MCP tools as an agent | [`scubiee-tools-and-usage.md`](scubiee-tools-and-usage.md) |
| Understand the `map` `find`/`focus` configs in depth | [`scubiee-map-configs.md`](scubiee-map-configs.md) |
| Install on Windows with GPU (DirectML) | [`scubiee-install-windows-dml.md`](scubiee-install-windows-dml.md) |

## Reference — product & architecture

- **[`scubiee-overview.md`](scubiee-overview.md)** — system overview: what it is,
  package layout, processes/lifecycle, retrieval architecture, storage/freshness,
  the MCP/HTTP/CLI surfaces, env vars. The single best starting point.
- **[`scubiee-tools-and-usage.md`](scubiee-tools-and-usage.md)** — the shipped MCP
  surface (`map` with `find`/`focus`, plus `gate`/`status`), the usage flow, and
  why it saves tokens.
- **[`scubiee-map-configs.md`](scubiee-map-configs.md)** — the design study behind
  the two shipped configs.
- **[`scubiee-blue-green-index-design.md`](scubiee-blue-green-index-design.md)** —
  zero-downtime forced-reindex (staged blue/green promote) design.

## Install & operations

- **[`scubiee-install-windows-dml.md`](scubiee-install-windows-dml.md)** — the
  Windows/DirectML install, including the `uv` override that keeps GPU
  acceleration from breaking on reinstall/upgrade.
- **[`windows-antivirus-guide.md`](windows-antivirus-guide.md)** — Windows AV
  exclusions / friction.
- **[`scubiee-action-matrix.md`](scubiee-action-matrix.md)** — operational
  guardrails for command sequences (e.g. the two different stop commands).

## Performance & reliability (v0.3.144 verification)

- **[`scubiee-performance-timings.md`](scubiee-performance-timings.md)** — measured
  tool-latency, cold-start, idle-recovery, and all sync-type timings on
  Windows/DML. The numbers other platforms are compared against.
- **[`scubiee-adversarial-stress-findings.md`](scubiee-adversarial-stress-findings.md)**
  — the 8-scenario adversarial MCP stress harness: what it attacks, bugs found +
  fixed, and the reliability-hardening fixes (health-under-load, delete-first
  drain, huge-file guard, offline prune, cold-start, the known-open rename item).
- **[`scubiee-scenario-test-matrix.md`](scubiee-scenario-test-matrix.md)** +
  **[`scubiee-scenario-test-results.md`](scubiee-scenario-test-results.md)** —
  real-world engine scenarios and their results.
- **[`scubiee-windows-reliability-results.md`](scubiee-windows-reliability-results.md)**
  — Windows reliability run (crash/restart/poll numbers).

## macOS

- **[`scubiee-macos-changelog-0.3.146.md`](scubiee-macos-changelog-0.3.146.md)** —
  what changed in 0.3.146: the one fix (pin `requires-python>=3.11`) that kills the
  intermittent MLX init heap-corruption crash, plus the kept MLX hygiene changes.
- **[`scubiee-macos-python-pin-fix-0.3.146.md`](scubiee-macos-python-pin-fix-0.3.146.md)** —
  root-cause writeup: the init crash was a Python-3.10/numpy-2.2.6 ABI mismatch,
  not an MLX bug; proven by 8/8 crash on 3.10 vs 20/20 clean on 3.12.
- **[`scubiee-macos-handoff-0.3.145.md`](scubiee-macos-handoff-0.3.145.md)** — the
  current handoff: step-by-step plan for a macOS agent to repeat the v0.3.145
  reliability + perf verification on MLX/Metal (now also covering the
  connect-once/init-auto-applies hardening), find/fix Mac-specific bugs, and
  report. **This supersedes the older mac test plans in the archive.**
- **[`scubiee-macos-findings-0.3.144.md`](scubiee-macos-findings-0.3.144.md)** —
  the completed Apple-Silicon (M5) findings from the 0.3.144 pass: four Mac bugs
  found, root-caused, and fixed. Historical record of what the Mac run verified.
- **[`scubiee-macos-warm-segfault-fix.md`](scubiee-macos-warm-segfault-fix.md)** —
  the macOS warm-start SIGSEGV root cause + fix (serialized native warm build).

---

## Archive

Historical docs, grouped by theme under [`archive/`](archive/). Kept for history
and provenance; **not** current product truth.

| Folder | What's in it |
|---|---|
| `archive/handoffs/` | Session/release handoffs from 0.2.x–0.3.1xx |
| `archive/mac-sessions/` | Older macOS test plans/findings, MLX index reports, pre-0.3.144 mac verification |
| `archive/ab-experiments/` | Retrieval A/B studies: map configs/arms, 2config, cursor/kiro adoption, token A/B, size/budget studies, old MCP evals |
| `archive/qa-bug-reports/` | Dated QA/bug/sync/beta reports and prior production-readiness writeups (superseded by the current perf/stress docs) |
| `archive/research/` | Architecture/retrieval research, MCP workspace-resolution research, parser/metadata phases, legacy design notes |
| `archive/test-matrices/` | CLI/connect e2e manual-test matrices, lifecycle & user-journey scenarios |
| `archive/pre-v3-pack-ladder/` | Docs for the retired 8-tool pack/expand/collect/workspace ladder |
| `archive/pre-v3-map-v2-iterations/` | Map V2 design iterations (superseded by Map V3 `find`/`focus`) |

> The retired MCP tool implementation itself (the pre-v3 pack ladder) is archived
> in the codebase under `archive/old-mcp-map/`, separate from these docs.

## Other doc folders

- `architecture/`, `engg/`, `perf/`, `reindexing/` — deeper engineering notes.
- `brand/`, `web-info/` — website/brand copy and changesets.
- `plans/`, `superpowers/`, `session-info/`, `sessions-learning/`, `research/` —
  working notes and learnings.
