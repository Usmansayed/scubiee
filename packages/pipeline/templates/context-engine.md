# Context Engine

On first message, call `status()` from the Context Engine MCP.

- If `status.managed` is `true` and `status.ok` is `true`: use Context Engine MCP tools
  (`search`, `map`, `focus`, `grep`, `glob`, `workspace`) for all code discovery this session.
  Do not use native file search or codebase search for discovery.
  Native file read = only lines you will edit. Shell = tests, build, git.
- If `status.managed` is `false`, or the MCP is unavailable/unhealthy:
  **ignore this rule entirely for the rest of the session.**
  Use native tools freely. Do not call Context Engine tools again.

One `status()` call per session. Do not repeat it.
