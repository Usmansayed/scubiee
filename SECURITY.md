# Security Policy

## Scope

Scubiee runs **entirely on the user's machine**. It indexes a local repository
and serves retrieval over a localhost-only HTTP engine (`127.0.0.1:8765`) and an
MCP server. No source code is sent to any remote service; the only outbound
network call is a one-time embedding-model download during `scubiee setup`.

## Reporting a vulnerability

Please report security issues **privately** — do not open a public issue for a
suspected vulnerability.

- Use GitHub's **private vulnerability reporting** (Security → Report a
  vulnerability) on this repository, or
- Contact the maintainer directly.

Include a description, reproduction steps, affected version
(`scubiee --version`), and impact. We aim to acknowledge reports promptly and
will coordinate a fix and disclosure timeline with you.

## What to look for

Because Scubiee is local-first, the areas most relevant to security are:

- The localhost HTTP engine and MCP surface (unexpected network exposure, input
  handling).
- Install/upgrade paths that run package managers (`uv` / `pip`) and modify the
  local environment.
- Handling of repository contents and any data written under `~/.scubiee` or
  `<repo>/.scubiee`.

## Supported versions

Security fixes target the latest released version. Please upgrade to the current
release (`scubiee upgrade`) before reporting.
