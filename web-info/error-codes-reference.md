# Error codes & messages reference

JSON `error` fields, CLI exit codes, and MCP status fields — what they mean and what to do.

**Version:** 0.3.14 · **Fix steps:** [complete-fix-guide.md](./complete-fix-guide.md)

---

## CLI exit codes

| Code | Meaning | Typical cause |
|------|---------|---------------|
| `0` | Success | — |
| `1` | Error | Check JSON `error` / stderr |
| `2` | Safety pause | Confirm required — not a crash |

**Exit 2 examples:**

- `scubiee wipe` without `--confirm`
- `scubiee wipe --all` without confirm
- Large `init`/`sync` without `--confirm`

**Fix:** Re-run with `--confirm` or answer prompt.

---

## Setup & machine errors

| Error | Meaning | Fix |
|-------|---------|-----|
| `machine_not_setup` | No `accel.json` / setup incomplete | `scubiee setup --repair` |
| `not_configured` | Preflight: embed stack missing | `setup --repair` |
| (preflight) missing fastembed | ORT/embed wheels absent | `setup --repair` |

---

## Enrollment & path errors

| Error | Meaning | Fix |
|-------|---------|-----|
| `unmanaged` | Repo not enrolled for this operation | `scubiee init .` |
| `requires_initialize` | Action needs prior init | `scubiee init .` |
| `path_too_broad` | Tried to index home/root | `cd` into project |
| `inside_ce_home` | Cannot init inside CTX_HOME | Use normal repo path |
| `confirm_required` | >400 files or wipe without confirm | Add `--confirm` |
| `never_index` | Path on block list | Clear never-index or pick other path |
| `unknown_project` | project_id not in registry | `init` or `list` to reconcile |
| `project_id_mismatch` | id.json ≠ registry expectation | `wipe --confirm` + re-init |
| `registry_conflict` | Concurrent registry mutation failed | Retry; check daemon |
| `path_missing` | Registry path no longer exists | `remove` or `locate` |

---

## Lifecycle errors

| Error | Meaning | Fix |
|-------|---------|-----|
| `paused` | Repo paused; sync-now blocked | `scubiee activate .` |
| `confirmation_mismatch` | Dashboard forget wrong id typed | Re-type exact `ce_…` |
| `forget_not_allowed` | Retention: repo still “present” | Wait or use CLI wipe |
| `store_delete_failed` | Could not rm project store | Close locks; retry wipe |

---

## MCP / engine errors (common in tool JSON)

| Error / field | Meaning | Fix |
|---------------|---------|-----|
| `managed: false` | Workspace not enrolled | `init` + `connect` + reload MCP |
| `ok: false` + `warming: true` | Daemon starting | Retry locate tool once |
| `ok: false` + `paused: true` | Global stop | User: `scubiee resume` |
| `repo_not_activated` | Repo paused or not ready | `activate` or `init` |
| `open_repo_failed` | Engine cannot open runtime | `engine ensure . --wait 45` |
| `overlapping_span` | Bad focus range | Fix start/end lines |
| Global stop hint | “Run scubiee resume” | User action required |

Agent-facing **not managed** text:

> Repository at … is not managed by Scubiee.

→ Same as `managed: false`.

---

## Wipe errors

| Error | Meaning | Fix |
|-------|---------|-----|
| `confirm_required` | Wipe blocked for safety | `--confirm` or TTY yes |
| `warning` + `needs_confirm: true` | Repo wipe preview only | Re-run with confirm |

---

## Upgrade errors

| Error | Meaning | Fix |
|-------|---------|-----|
| `pypi_unreachable` | No network to PyPI | Check network; retry upgrade |
| `package_upgrade_failed` | pip/uv swap failed | `unlock-tool`; manual reinstall |
| `version_mismatch` | Daemon version ≠ installed CLI | `engine restart` or `upgrade` |

---

## CTX_HOME guard

| Error | Meaning | Fix |
|-------|---------|-----|
| `ctx_home_polluted` | CTX_HOME looks like real home dir in tests | Set proper test home or `CTX_ALLOW_TEST_HOME=1` |

---

## Doctor / install identity fields (0.3.13+)

Not errors — interpret in `scubiee doctor .`:

| Field | Good | Problem |
|-------|------|---------|
| `binaries_match` | `true` | Wrong scubiee binary invoked |
| `multiple_installs` | `false` | Extra scubiee on PATH — pick one install |
| `expected_binary` | Matches uv Scripts path | Double `Scripts\Scripts` was bug in 0.3.13; fixed 0.3.14 |

---

## Status JSON fields (MCP / CLI)

| Field | Values | Meaning |
|-------|--------|---------|
| `enrolled` | bool | Repo in registry |
| `state` | `active`, `paused`, `unmanaged`, … | Lifecycle |
| `managed` | bool | MCP: safe to use Scubiee tools |
| `ok` | bool | Daemon healthy |
| `warming` | bool | Starting — retry tool, don't poll status |
| `should_use_mcp` | bool | Agent guidance |
| `next_action` | string | CLI command user should run |
| `lifecycle_state` | string | From lifecycle guidance engine |

---

## Diagnose JSON sections

Use [complete-fix-guide.md](./complete-fix-guide.md) triage. Key sections:

| Section | If bad |
|---------|--------|
| `acceleration.profile` | `setup --repair` |
| `libraries.fastembed` / `onnxruntime` | `setup --repair` |
| `capabilities.missing_required` | install missing deps |
| `install.multiple_installs` | consolidate PATH |
| `mcp.connected` | `connect --cursor` |

---

## Related

- [complete-fix-guide.md](./complete-fix-guide.md)
- [data-and-files-reference.md](./data-and-files-reference.md)
- [../docs/web-info/troubleshooting.md](../docs/web-info/troubleshooting.md)
