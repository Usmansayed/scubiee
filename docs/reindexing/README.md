# Reindexing — decision docs

Working folder for **when / how** Context Engine refreshes graph + semantic indexes while agents rely on CE tools.

| Doc | Status | What it is |
|-----|--------|------------|
| **[live-reindexing-system-design.md](./live-reindexing-system-design.md)** | **LOCKED** | Final live reindexing system design (source of truth) |
| **[chunk-level-incremental-indexing.md](./chunk-level-incremental-indexing.md)** | **IMPLEMENTED** | File-level dirty detection; chunk-level vector reuse and embedding |
| [index-freshness-agent-trajectory.md](./index-freshness-agent-trajectory.md) | Research appendix | Options menu / recipes A–D |
| [agent-write-patterns-and-channel-conflicts.md](./agent-write-patterns-and-channel-conflicts.md) | Research appendix | Agent write frequencies; dirty-set; BM25 vs dense conflicts |
| **[future-work.md](./future-work.md)** | **BACKLOG** | Production issues we will not implement now (search-path pollution, project-id churn, dump/replace, MCP health) |

Implement against the locked design only.
