# Heatmap-only pack vs agent-needed reads

**Task:** When I connect Scubiee to Cursor, I need to understand the full path that writes MCP config and permissions so the agent can call tools.

**Enrich:** `connect cursor install mcp config permissions allowlist autoApprove project rules gate text write tool surface so agent can call locate pack`

## Summary

- Pack MCP JSON size: **3696** chars (no code bodies: `True`)
- Agent would read: **13638** chars across 7 spans
- Compression ratio (pack/agent): **0.271**
- Exact span cover (full heatmap): **0.429**
- Exact span cover (read.top=5): **0.143**
- Missing from heatmap: **1**

## Pack heatmap (MCP view)

- r=1 heat=hot `packages/pipeline/rules_installer.py:1312-1374` `write_project_tool_surface` sc=1.0
- r=2 heat=hot `packages/pipeline/rules_installer.py:682-712` `_write_mcp_json_keyed` sc=1.0
- r=3 heat=hot `packages/pipeline/rules_installer.py:333-352` `_load_json_for_merge` sc=1.0
- r=4 heat=hot `packages/pipeline/rules_installer.py:676-679` `_write_json` sc=1.0
- r=5 heat=warm `packages/pipeline/branding.py:24-26` `strip_legacy_mcp_keys` sc=1.0
- r=6 heat=warm `packages/pipeline/rules_installer.py:1139-1202` `write_project_gate_rules` sc=1.0
- r=7 heat=warm `packages/pipeline/mcp_permissions.py:158-159` `tool_permission_plan` sc=0.9967
- r=8 heat=warm `packages/pipeline/rules_installer.py:532-629` `_write_workspace_mcp` sc=0.99
- r=9 heat=cold `packages/pipeline/rules_installer.py:266-280` `gate_line_for_repo` sc=0.99
- r=10 heat=cold `packages/pipeline/rules_installer.py:283-289` `_project_rules_eligible` sc=0.99
- r=11 heat=cold `packages/pipeline/rules_installer.py:1109-1122` `_write_rule_append_md` sc=0.99
- r=12 heat=cold `packages/pipeline/rules_installer.py:1133-1136` `_write_rule` sc=0.99

**read guidance:** {'top': 5, 'how': 'Native-Read loc for top ~5 (heat=hot first, then warm). Spans only (file:start-end) — BAN whole-file Read. expand_context if a hop is missing; collect_hot_context(ids=) only when you need bodies batched.'}

## Agent needed

- `packages/pipeline/__main__.py:1706-1744` — cmd_connect entry (1567 chars)
- `packages/pipeline/rules_installer.py:1560-1640` — install_tool fan-out (2690 chars)
- `packages/pipeline/rules_installer.py:1487-1553` — apply_connected_tools_to_repo (2241 chars)
- `packages/pipeline/rules_installer.py:1312-1374` — write_project_tool_surface (2264 chars)
- `packages/pipeline/rules_installer.py:1139-1202` — write_project_gate_rules (2152 chars)
- `packages/pipeline/mcp_permissions.py:518-531` — apply_permissions_to_repo_tool_surface (397 chars)
- `packages/pipeline/mcp_permissions.py:253-320` — merge_cursor_permissions (2327 chars)

## Missing from heatmap

- `packages/pipeline/__main__.py:1706-1744` — cmd_connect entry

Full JSON: `docs/superpowers/plans/2026-09-06-heatmap-pack-vs-agent-reads.json`
