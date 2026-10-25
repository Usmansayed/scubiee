# Getting help with Scubiee

## Where to go

| You have… | Go here |
|---|---|
| A **usage question** ("how do I…?") | Check the [docs](docs/README.md), the [FAQ](docs/web-info/faq.md), and [troubleshooting](docs/web-info/troubleshooting.md) first. If they don't answer it, open an [issue](https://github.com/Usmansayed/scubiee/issues/new/choose) and describe what you're trying to do. |
| A **reproducible bug** | Open a [bug report](https://github.com/Usmansayed/scubiee/issues/new?template=bug_report.yml). |
| A **feature idea** | Open a [feature request](https://github.com/Usmansayed/scubiee/issues/new?template=feature_request.yml). |
| A **security vulnerability** | **Do not open a public issue.** Report it privately as described in [SECURITY.md](SECURITY.md). |

Useful starting points:

- [Getting started](docs/web-info/getting-started.md)
- [Install and debug](docs/web-info/install-and-debug.md)
- [Commands reference](docs/web-info/commands-reference.md)
- [scubiee.com](https://scubiee.com)

## Help us help you

When you ask for help, include:

- Your Scubiee version: `scubiee --version`
- Your OS, Python version, and accelerator (CUDA / DirectML / MLX / CPU)
- The IDE or MCP client you use (Cursor, Claude Code, Kiro, …)
- Steps to reproduce, and what you expected to happen
- Sanitized logs — `scubiee doctor .` output, or a diagnostic bundle from
  `scubiee diagnose --no-tests --desktop`, plus the relevant tail of `~/.scubiee/engine.log`

## Keep sensitive data out of public posts

Issues are public. Before posting, remove API keys, tokens, passwords, internal hostnames, and
private source code from logs and screenshots.

Scubiee is maintained mainly by one person, so replies may take a few days. Thanks for your
patience.
