# Context Agent (Qwen3-1.7B + Context Engine tools)

Local **retrieval orchestrator** — not a coder. Uses llama.cpp (Vulkan) + CE/Graphify tools, returns a context pack for the main agent.

## Start llama.cpp

```powershell
.\scripts\context_agent\start_llama_qwen.ps1
# Model default: C:\Users\usman\models\Qwen3-1.7B-Q4_K_M.gguf
# API: http://127.0.0.1:8080/v1
```

## Run

```powershell
$env:PYTHONPATH = "packages"
$env:CTX_LLAMA_URL = "http://127.0.0.1:8080"
$env:CTX_RETRIEVE = "D"
.\.venv\Scripts\python.exe -m pipeline.context_agent `
  "browser lease busy contention guidance" `
  --repo testdata/cursor_sdk_ab/work_d_channel_best_mcponly `
  -v --out out/context_agent_pack.json
```

## Design

- System prompt: JSON-only tool loop (`search_code` → graph/grep/span → `done`)
- Max ~5 tool rounds; builds `{files, snippets, summary, tool_trace}`
- Main coding agent should consume the pack, not re-discover from scratch
