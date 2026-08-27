<!-- scubiee:start -->
# Scubiee

**Start of session:** call `status()` from the Scubiee MCP.

- If `status.managed` is `true` and `status.ok` is `true`: use Scubiee MCP tools
  (`search`, `map`, `focus`, `grep`, `glob`, `workspace`) for all code discovery this session.
  Do not use native file search or codebase search for discovery.
  Native file read = only lines you will edit. Shell = tests, build, git.
- If `status.managed` is `true` and `status.warming` is `true`: the engine is starting up.
  Use Scubiee MCP tools — if a tool returns warming/not-ready, wait 5s and retry once.
- If `status.managed` is `false`, or the MCP is unavailable/unhealthy: use native tools for now.
  **Do not permanently disable Scubiee for this session.**

**Retry `status()`** when the user runs `scubiee init` / `scubiee connect`, asks to index or use
Scubiee, or asks whether this repo is managed / to check Scubiee — then switch to Scubiee MCP
if `managed` becomes `true`. If a tool returns `should_retry_status`, call `status()` again.

<!-- scubiee:end -->
