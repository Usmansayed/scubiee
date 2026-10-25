# Security Policy

## Scope

Scubiee runs **on the user's machine** and works with private source code. It indexes a local
repository and serves retrieval over a localhost-only HTTP engine (`127.0.0.1:8765` by default)
and an MCP server used by AI coding tools. Source code is not sent to any remote service by
Scubiee; the only outbound network step is the embedding-model download during `scubiee setup`
(and package downloads during `scubiee upgrade`).

Areas most relevant to security:

- The localhost HTTP engine and the MCP server (unexpected network exposure, input handling,
  path traversal outside the indexed repository).
- Install, setup, and upgrade paths that run package managers (`uv` / `pip`) and modify the local
  environment or IDE configuration files.
- Data written under `~/.scubiee` and `<repo>/.scubiee`, including indexes and embedding caches
  derived from source code.
- Agent rule and MCP configuration files that `scubiee connect` writes for IDEs.

## Reporting a vulnerability

Please report security issues **privately**. Do **not** disclose a suspected vulnerability in a
public GitHub issue, discussion, or pull request.

- **Preferred:** GitHub private vulnerability reporting — open the repository's
  [Security tab](https://github.com/Usmansayed/scubiee/security) and choose
  **Report a vulnerability**.
- **Alternative:** email [team@scubiee.com](mailto:team@scubiee.com) with "Security" in the
  subject line.

Please include, where safe:

- A description of the vulnerability and its potential impact.
- Affected versions (`scubiee --version`) or commits.
- Steps to reproduce, and a minimal proof of concept if you have one.
- Your OS, Python version, and the IDE / MCP client involved, if relevant.
- Suggested mitigations, if known.

Do not send real credentials, other people's data, or private source code. If something sensitive
is truly needed to reproduce the issue, say so in your first message and we'll agree on a secure
way to share it.

## What to expect

Scubiee is maintained mainly by one person, so these are targets, not guarantees:

- Acknowledge your report within **7 calendar days**.
- Assess severity and which versions are affected.
- Investigate and develop a fix where appropriate, and keep you updated on progress.
- Coordinate the disclosure timing with you.
- Publish a fix release and, where appropriate, a GitHub security advisory crediting you (unless
  you prefer to stay anonymous).

Please give us reasonable time to investigate and release a fix before any public disclosure.

Scubiee does not currently offer a bug bounty.

## Supported versions

Security fixes are made for the **latest released version** only. Please upgrade
(`scubiee upgrade`, or `pip install -U scubiee`) and confirm the issue still reproduces before
reporting.
