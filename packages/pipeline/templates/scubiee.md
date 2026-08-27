# Scubiee

**Start of session:** call `status()` once from the Scubiee MCP. Do not call it every turn.

- If `status.managed` is `true` and `status.ok` is `true`: use Scubiee MCP tools
  (`search`, `map`, `focus`, `grep`, `glob`, `workspace`) for all code discovery this session.
  Do not use native file search or codebase search for discovery.
  Native file read = only lines you will edit. Shell = tests, build, git.
- If `status.managed` is `true` and `status.warming` is `true`: the engine is starting up.
  Use Scubiee MCP tools — if a tool returns warming/not-ready, wait 5s and retry once.
- If `status.paused` is `true`: tell the user to run `scubiee resume`. Do not poll `status()`.
- If `status.managed` is `false`, or the MCP is unavailable/unhealthy: use native tools for now.
  **Do not permanently disable Scubiee for this session.**

**Retry `status()` only when** (never every turn / never in a loop):
- the user runs `scubiee init` / `scubiee connect` / `scubiee resume`, or asks to index or use Scubiee
- the user asks whether this repo is managed / to check Scubiee
- a Scubiee tool returns `should_retry_status: true` after init/connect was likely done

Then switch to Scubiee MCP if `managed` becomes `true`.
