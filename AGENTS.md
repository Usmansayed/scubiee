<!-- scubiee:start -->
# Scubiee

**All MCP hosts:** server instructions start with `GATE 0` or `GATE 1:ce_…`; every tool JSON has `"g"`. Read those — do not call `gate()` or `status()` for managed checks.

- `1:ce_…` → use Scubiee MCP for discovery. `0` → native tools.

Pass `root` on locate when the host gives a Workspace Path. Use `status()` only for engine health.

<!-- scubiee:end -->
