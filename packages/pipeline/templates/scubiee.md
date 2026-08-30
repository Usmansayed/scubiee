# Scubiee GATE — short locate guide

Short guide here; full workflow is in Scubiee MCP server instructions.

- **GATE 0** (not managed): BAN Scubiee locate tools. USE native Grep/Glob/Read/search. Run `scubiee init .` to enroll.
- **GATE 1:ce_*** (managed): Prefer Scubiee `map`|`focus`|`grep`|`glob` for discovery. Native Grep/Glob/Read OK for known paths or full-file reads. `focus` budget: `cap` (~400 lines) · `wide` (20k chars) · `full` (100k chars). Edit/Shell for changes/tests.
- **GATE p**: `scubiee resume`.

Pass `session_id` from Scubiee responses on later calls.
