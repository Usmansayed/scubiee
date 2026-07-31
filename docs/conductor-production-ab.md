# Conductor production A/B — Graphify vs D_rerank

**Final architecture:** [`conductor-final-architecture.md`](conductor-final-architecture.md) — ship **`D_rerank`**. Soft routers (`r_gated`, `d_floor`) stay experimental only.

## What you get

| Surface | Entry | Use |
|---------|-------|-----|
| HTTP API | `conductor_api.py` | curl / scripts / dashboards |
| MCP (Cursor) | `conductor_mcp.py` | Ask the agent to `conductor_compare` |

Shared engine: `packages/conductor/service.py` (loads corpus once).

## Prerequisites

- Ollama with `nomic-embed-text` (`http://localhost:11434`)
- Corpus defaults to `testdata/frontend-mcp` + embed cache under `out/`

## HTTP API

```powershell
cd C:\Users\usman\Downloads\context-engine
$env:PYTHONPATH = "packages"
.\.venv\Scripts\python -u conductor_api.py
```

```powershell
# health
Invoke-RestMethod http://127.0.0.1:8765/health

# A/B compare
$body = @{ query = "where is the playbook selector"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8765/compare -Method Post -Body $body -ContentType "application/json"
```

Endpoints:

- `GET /health`
Endpoints:

- `GET /health`
- `POST /search` `{ query, top_k, mode: graphify|d_rerank|d_floor|r_gated|both|both_rg }`
- `POST /compare` — Graphify vs **D_rerank** + agreement
- `POST /compare_rgated` — **D_rerank vs R_gated** + agreement (soft-router A/B)

Production default remains **`d_rerank`**.  
Experimental soft routers: `r_gated` (preferred) or `d_floor` (blunt). See Soft R&D#4/#5 in `docs/conductor-top3-rd.md`.

OpenCode soft-router brief: [`docs/opencode-rgated-instructions.md`](opencode-rgated-instructions.md).

## Soft bake-off

```powershell
$env:PYTHONPATH = "packages;."
.\.venv\Scripts\python -u scripts\run_soft_arch_bakeoff.py
```

Report: `out/conductor_soft_bakeoff.json`.

## MCP in Cursor

Add to Cursor MCP settings (`mcp.json`):

```json
{
  "mcpServers": {
    "conductor-ab": {
      "command": "C:/Users/usman/Downloads/context-engine/.venv/Scripts/python.exe",
      "args": ["-u", "C:/Users/usman/Downloads/context-engine/conductor_mcp.py"],
      "env": {
        "PYTHONPATH": "C:/Users/usman/Downloads/context-engine/packages;C:/Users/usman/Downloads/context-engine"
      }
    }
  }
}
```

Tools:

- `conductor_compare(query, top_k)` — **primary** for A/B
- `conductor_search(query, mode, top_k)`
- `conductor_status()`

## How to judge in production

For each real coding question:

1. Call `conductor_compare`
2. Note `agreement.same_top1` and which list has the file you actually open
3. Prefer **D_rerank** if it wins more often on paraphrases; prefer **graphify** if D never helps and only adds latency

Keep a simple tally (e.g. 20 queries): graphify-only useful / d_rerank-only useful / tie.
