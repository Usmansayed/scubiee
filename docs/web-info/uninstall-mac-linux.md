# Uninstall (Mac & Linux)

Remove Scubiee from a machine without the Windows-specific uv lock issues (though quitting Cursor is still recommended).

---

## Standard full uninstall

```bash
scubiee stop
scubiee wipe --all --yes --package
```

Then reload Cursor MCP (or restart Cursor).

If installed via **uv tool**:

```bash
uv tool uninstall scubiee
```

If installed via **pip** in a venv:

```bash
/path/to/venv/bin/pip uninstall scubiee -y
```

Use the Python path printed by `scubiee --version`.

---

## Wipe options

| Flag | Effect |
|------|--------|
| `--all --yes` | Delete all CE state (indexes, registry, MCP wiring, rules) |
| `--package` | Also uninstall scubiee package |
| `--keep-models` | Keep CodeRank / FastEmbed download cache |
| `--keep-package` | Wipe state but leave CLI installed |

Examples:

```bash
scubiee wipe --all --yes --keep-models --package
scubiee wipe --all --yes --keep-package    # reset CE but keep CLI
```

---

## Repo-only wipe (keep other projects)

```bash
cd /path/to/repo
scubiee wipe .
# or
scubiee remove . --delete-store
```

Removes that repo’s `.context-engine/id.json`, Cursor rule snippet, and index store entry.

---

## Manual cleanup (if CLI broken)

```bash
rm -rf ~/.context-engine
# edit ~/.cursor/mcp.json — remove "context-engine" from mcpServers
uv tool uninstall scubiee
```

Mac repair from git checkout (if you have the repo):

```bash
# no Windows-only scripts needed; reinstall uv tool from PyPI
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple
scubiee setup --repair
```

---

## Reinstall fresh

```bash
uv tool install scubiee==0.2.82 --index-url https://pypi.org/simple
scubiee setup --repair
cd your/project && scubiee init . --fast
```

---

## Windows

See [Uninstall on Windows](./uninstall-windows.md) for Access denied / MCP file locks.

---

## Related

- [Getting started](./getting-started.md)
- [Troubleshooting](./troubleshooting.md)
