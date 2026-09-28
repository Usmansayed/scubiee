import json
from pathlib import Path

d = json.loads(
    Path(
        r"C:\Users\usman\Downloads\context-engine\docs\superpowers\plans\2026-09-06-seed-pick-tool-retrieval-log.json"
    ).read_text(encoding="utf-8")
)

lines = [
    "# Seed-pick A/B — tool retrieval log + improvisation notes",
    "",
    "**Host tokens:** MCP Scubiee **448k** vs Native **543k** (~17.5% save).",
    "",
    "Full machine log: `docs/superpowers/plans/2026-09-06-seed-pick-tool-retrieval-log.json`",
    "",
    "## MCP Scubiee ([4195dc84](4195dc84-ba28-4fda-87dd-70c3b49f81a4))",
    "",
    "### Tool mix",
    "",
    "```",
    json.dumps(d["agents"]["mcp"]["tool_counts"], indent=2),
    "```",
    "",
    "### Retrieval timeline (UpdateCurrentStep omitted)",
    "",
]

for i, r in enumerate(d["agents"]["mcp"]["timeline"], 1):
    if r.get("kind") != "tool_use":
        continue
    t = r["tool"]
    s = r.get("summary") or {}
    if t == "UpdateCurrentStep":
        continue
    if t == "CallDynamicTool":
        lines.append(
            f"- `{i:02d}` **MCP `{s.get('tool')}`** "
            f"seed=`{s.get('seed_file','')}` sym=`{s.get('seed_symbol','')}` "
            f"mode=`{s.get('mode','')}` dir=`{s.get('direction','')}`"
        )
    elif t == "GetDynamicTools":
        lines.append(
            f"- `{i:02d}` GetDynamicTools ns=`{s.get('namespace')}` "
            f"tool=`{s.get('toolName')}` pat=`{s.get('pattern')}`"
        )
    elif t == "Read":
        p = str(s.get("path") or "").replace("\\", "/")
        if "context-engine/" in p:
            p = p.split("context-engine/")[-1]
        off = s.get("offset")
        lim = s.get("limit")
        lines.append(f"- `{i:02d}` Read `{p}` offset={off} limit={lim}")
    elif t == "Grep":
        lines.append(
            f"- `{i:02d}` Grep `{s.get('pattern')}` @ `{s.get('path')}`"
        )
    else:
        lines.append(f"- `{i:02d}` {t} {s}")

lines += [
    "",
    "## Native ([d67754a9](d67754a9-2a53-465c-9372-2cb21c74c334))",
    "",
    "### Tool mix",
    "",
    "```",
    json.dumps(d["agents"]["native"]["tool_counts"], indent=2),
    "```",
    "",
    "### Retrieval timeline (compressed — Grep/Read heavy)",
    "",
]

n_grep = n_read = 0
for i, r in enumerate(d["agents"]["native"]["timeline"], 1):
    if r.get("kind") != "tool_use":
        continue
    t = r["tool"]
    s = r.get("summary") or {}
    if t == "UpdateCurrentStep":
        continue
    if t == "Grep":
        n_grep += 1
        if n_grep <= 12:
            lines.append(
                f"- `{i:02d}` Grep `{s.get('pattern')}` @ `{s.get('path')}`"
            )
        elif n_grep == 13:
            lines.append("- … (more Greps)")
    elif t == "Read":
        n_read += 1
        p = str(s.get("path") or "").replace("\\", "/")
        if "context-engine/" in p:
            p = p.split("context-engine/")[-1]
        if n_read <= 15:
            lines.append(
                f"- `{i:02d}` Read `{p}` offset={s.get('offset')} limit={s.get('limit')}"
            )
        elif n_read == 16:
            lines.append("- … (more Reads)")
    elif t == "Glob":
        lines.append(f"- `{i:02d}` Glob `{s.get('glob')}`")

lines += [
    "",
    "## Where MCP still burned tokens",
    "",
    "1. **4× GetDynamicTools** — schema discovery before each MCP call (should cache once).",
    "2. **7× UpdateCurrentStep** — UI chrome, not locate value.",
    "3. **7× Grep after heatmap** — still shotgunning after pack; pack was only ~620 chars.",
    "4. **9× Read** — more than `read.top=5` (heatmap had 2 hot cards; agent over-read).",
    "5. **expand_context** — extra MCP hop after a thin-but-usable pack.",
    "6. Model reasoning turns between tools — host tokens ≫ tool chars (~18.5k chars vs 448k tokens).",
    "",
    "## Improvisation backlog (product + agent policy)",
    "",
    "| Change | Why |",
    "|---|---|",
    "| Agent: **one** GetDynamicTools per namespace, then call | Cut schema rediscovery |",
    "| Agent: hard stop after map+pack+≤5 Reads unless expand justified | Cap thrash |",
    "| Agent: ban Grep until top heats Read | Force heatmap use |",
    "| Product: fix MCP `suggested_seed` null (cards need kind/symbol) | Fewer wrong seeds / expands |",
    "| Product: denser heatmap when seed known (include resolve_seed_node neighbors) | One pack enough |",
    "| Skip UpdateCurrentStep in eval agents | Pure token noise |",
    "| Log tool_use + response_chars in harness automatically | Repeatable A/Bs |",
    "",
]

out = Path(
    r"C:\Users\usman\Downloads\context-engine\docs\superpowers\plans\2026-09-06-seed-pick-tool-retrieval-log.md"
)
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("wrote", out)
print("mcp tools", d["agents"]["mcp"]["tool_counts"])
print("native tools", d["agents"]["native"]["tool_counts"])
