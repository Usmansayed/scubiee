# Cursor subagent A/B — same mission, different search stack

**Repo:** `C:\Users\usman\Downloads\context-engine\testdata\frontend-mcp`

## Tasks (complete all 3)

### T1
Find:
1. Where the AGENT is told what to do when a browser session vanished/unreachable
2. The lease/queue owner that stops two perception tools sharing one browser unsafely
3. Where MCP tool names are bound to callables after an executor picks a name

End with three repo-relative paths. Avoid SEO/Figma/dribbble rabbit holes.

### T2
For each file, show a SMALL snippet (few lines) supporting: guidance → session lease → dispatch registry. One-sentence wiring story.

### T3
Name one symbol in `browser_session_manager` for acquire/lease, and one in `dispatch_registry` for tool name → callable. Quote a few lines.

## Rubric (must appear in final answer text)
- T1/T2: `agent_guidance.py`, `browser_session_manager.py`, `dispatch_registry.py`
- T3: `browser_session_manager.py`, `dispatch_registry.py`
- Avoid citing paths under `seo/` or `dribbble/` as the answer

## Return JSON at end
```json
{
  "arm": "ce_mcp | graphify",
  "tool_calls": {"search_mcp": N, "graphify_cli": N, "read": N, "grep": N, "other": N},
  "payload_chars": approximate chars returned by search/graph tools only,
  "rubric_pass": "N/3",
  "turns": [{"id":"T1","paths":[...],"ok":true}, ...],
  "final_answer": "short summary",
  "wall_notes": "anything notable"
}
```
