<!-- context-engine:start -->
# Scubiee

On first message, call `status()` from the Scubiee MCP.

- If `status.managed` is `true` and `status.ok` is `true`: use Scubiee MCP tools
  (`search`, `map`, `focus`, `grep`, `glob`, `workspace`) for all code discovery this session.
  Do not use native file search or codebase search for discovery.
  Native file read = only lines you will edit. Shell = tests, build, git.
- If `status.managed` is `false`, or the MCP is unavailable/unhealthy:
  **ignore this rule entirely for the rest of the session.**
  Use native tools freely. Do not call Scubiee tools again.

One `status()` call per session. Do not repeat it.

<!-- context-engine:end -->
