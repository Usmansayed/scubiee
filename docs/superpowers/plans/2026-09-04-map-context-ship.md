# Live MCP smoke — Context Tracing tools

```powershell
# Reload Scubiee MCP in Cursor after pull (or restart MCP server).
# Tools: map_context | expand_context | collect_hot_context

# Fixture-quality call (guide only):
map_context(
  query="I am debugging login auth. Collect credential check + user load hops; skip analytics.",
  seed_file="fixtures/trace-lab/app/middleware/auth.py",  # or app/... if cwd is fixtures
  seed_symbol="authenticate",
  seed2_file="fixtures/trace-lab/app/services/jwt_service.py",
  seed2_symbol="JwtService.verify"
)

# Then native Read hot file:line ranges from the heatmap.
# If thin: expand_context(node="file::symbol", direction="callees")
# Rare: collect_hot_context(threshold=0.82)
```

Backend smoke (no MCP host):

```text
PYTHONPATH=packages python -c "from pipeline.context_trace import run_map_context; ..."
```

Design: `docs/superpowers/specs/2026-09-04-context-trace-mcp-tools-design.md`
