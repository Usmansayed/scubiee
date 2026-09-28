import json
from collections import Counter
from pathlib import Path

p = Path(
    r"C:\Users\usman\.cursor\projects\c-Users-usman-Downloads-context-engine"
    r"\agent-transcripts\7deb1043-a1f3-488a-8015-f0cb5de0118c\subagents"
    r"\9b2a0392-cb37-47d5-9392-cff533d48b62.jsonl"
)
tools = []
texts = []
for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip():
        continue
    try:
        ev = json.loads(line)
    except Exception:
        continue
    msg = ev.get("message") or {}
    role = ev.get("role")
    content = msg.get("content")
    if not isinstance(content, list):
        continue
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "tool_use":
            tools.append((part.get("name"), part.get("input") or {}))
        elif part.get("type") == "text" and role == "assistant":
            t = (part.get("text") or "").replace("\n", " ")
            if t.strip():
                texts.append(t[:220])

print("n_tool_use", len(tools))
print("counts", dict(Counter(n for n, _ in tools)))
print("--- timeline ---")
for i, (n, inp) in enumerate(tools, 1):
    if n == "CallDynamicTool":
        args = inp.get("arguments") or {}
        print(
            f"{i:02d} MCP {inp.get('toolName')} "
            f"seed={args.get('seed_file','')} sym={args.get('seed_symbol','')} "
            f"dir={args.get('direction','')} wb={args.get('with_bodies','')}"
        )
    elif n == "GetDynamicTools":
        print(
            f"{i:02d} GetDynamicTools ns={inp.get('namespace')} "
            f"tool={inp.get('toolName')} pat={inp.get('pattern')}"
        )
    elif n == "Read":
        path = str(inp.get("path") or "").replace("\\", "/")
        if "context-engine/" in path:
            path = path.split("context-engine/")[-1]
        print(f"{i:02d} Read {path} off={inp.get('offset')} lim={inp.get('limit')}")
    elif n == "Grep":
        print(f"{i:02d} Grep {str(inp.get('pattern') or '')[:70]} @ {inp.get('path')}")
    elif n == "Shell":
        print(f"{i:02d} Shell {str(inp.get('command') or '')[:120]}")
    elif n == "UpdateCurrentStep":
        print(f"{i:02d} UpdateStep {inp.get('current_step')}")
    else:
        print(f"{i:02d} {n}")

print("--- assistant notes ---")
for t in texts[:10]:
    print("-", t)
