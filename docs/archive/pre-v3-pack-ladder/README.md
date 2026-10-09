# Archive — pre-v3 "pack ladder" docs

These documents describe the **retired** Scubiee MCP locate surface, built around a multi-step
ladder:

```
map  →  pack_context(lean)  →  expand_context / collect_hot_context
```

implemented in the old `packages/pipeline/mcp_locate.py` (now at `archive/old-mcp-map/mcp_locate.py`).

## Why they are here

The product shipped **Map v3**, which replaced that ladder with a single `map` tool whose behavior
is chosen by a `config`:

- `map config=find` — ranked locations **with code inline** (top clustered files packed)
- `map config=focus` — a symbol's full body + callers + callees + file siblings, ready to edit
- `map config=related` — code related to an anchor chunk under a query, with bodies
- `map config=graph` — abstract files→symbols + call-edges map, no bodies, for orientation

plus `gate` / `status` for health. There is **no** `pack_context`, `expand_context`, or
`collect_hot_context` anymore. The server is `packages/pipeline/map_v3_server.py`.

## How to read these

Treat everything in this folder as a **point-in-time historical record** — beta issue lists, QA
findings, mac handoffs, A/B deep-dives, and the pre-v3 tool/overview reference docs. They are
accurate for the version they were written against. For the **current** surface see:

- `docs/scubiee-overview.md`
- `docs/scubiee-tools-and-usage.md`
- `docs/context-engine-mcp.md`

## Contents

| File | What it was |
|---|---|
| `scubiee-tools-and-usage.md` | Pre-v3 tool reference (the `map→pack→expand` ladder) — superseded |
| `scubiee-overview.md` | Pre-v3 system overview — superseded |
| `scubiee-bugs-found.md`, `scubiee-bugs-root-cause-and-fix-plan.md` | Pre-v3 bug lists tied to pack/expand |
| `scubiee-qa-findings.md`, `scubiee-macos-findings.md`, `scubiee-macos-test-plan.md` | Pre-v3 QA / mac test records |
| `scubiee-token-ab-deep-dive.md`, `claude-sdk-scubiee-token-ab-report.md` | A/B token studies against the old ladder |
| `beta-issues-2026-09-26.md`, `beta-open-issues-kiro-fix-2026-09-26.md`, `mcp-prepublish-findings-2026-09-22.md` | Dated beta/prepublish issue reports |
| `production-ready-0.3.131.md`, `production-issues-2026-09-24.md`, `macos-handoff-0.3.101.md` | Version-pinned status/handoff snapshots |
| `kiros-experience-using-scubiee.md` | Session narrative using the old ladder |
