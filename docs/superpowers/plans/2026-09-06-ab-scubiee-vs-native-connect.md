# A/B: Scubiee locate vs native-only (connect write path)

**Task:** When I connect Scubiee to Cursor, what is the write path that installs MCP config + permissions so the agent can call tools?

**Agents:** [Scubiee](117ff2a3-dc4d-4ba9-a492-3bc1e360e231) vs [Native](e9df725e-f035-4e1b-bb40-acad27028f90)

## Efficiency

| | Scubiee (map→pack→span Read) | Native (Grep/Glob/Read only) |
|---|---|---|
| tool_calls | 30 | 36 |
| chars ingested | ~46,000 | ~92,000 |
| ratio | **1.0×** | **~2.0×** more tokens |
| files span-read | 5 | 5 (+ tool_registry) |
| answer quality | same core path | same core path (+ a bit more detail) |

## Shared verdict (both correct)

`cmd_connect` → `install_tool` → `fan_out_tool_to_enrolled_repos` → `write_project_tool_surface` → `.cursor/mcp.json` (`_write_workspace_mcp` / `write_mcp_config`) + `.cursor/permissions.json` (`apply_permissions_to_repo_tool_surface` / `merge_cursor_permissions`).

## Notes

- Scubiee pack was thin (weak seeds `_templates_dir` / `interpreter`); map cards still steered Grep → ~half the token burn vs shotgun native.
- Cursor MCP was unavailable in parent chat; Scubiee agent used **CLI** map/pack (0.3.25).
- Native agent also found secondary `write_cursor_mcp` and `tool_registry` / `_TOOL_PLANS` detail.
