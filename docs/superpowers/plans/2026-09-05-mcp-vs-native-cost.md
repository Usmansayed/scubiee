# MCP vs native cost (time + tokens)

**n=5** problems from ten-problem set. Engine: `composite_v1`.
Token estimate: `chars/4`. Warmup compile: **20111.2 ms** (excluded from per-problem means).

| Path | mean wall ms | mean out tokens | mean tool calls | mean file_rec |
|------|-------------:|----------------:|----------------:|--------------:|
| native (rg+read) | 373.3 | 7619.4 | 8.0 | 0.0 |
| native_gold (oracle read) | 2.3 | 6766.2 | 2.0 | 1.0 |
| **mcp_lean** (map+pack+expand) | 12285.0 | 5980.8 | 3.0 | 0.5 |
| mcp_full (map+pack full) | 4448.5 | 5040.0 | 2.2 | 0.5 |

**native / mcp_lean:** tokens ×1.27, time ×0.03

Per-problem details: `docs/superpowers/plans/2026-09-05-mcp-vs-native-cost.json`.
