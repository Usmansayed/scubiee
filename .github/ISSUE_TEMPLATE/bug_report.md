---
name: Bug report
about: Report a problem with Scubiee
title: "[bug] "
labels: bug
---

**What happened**
A clear description of the bug and what you expected instead.

**Steps to reproduce**
1. …
2. …

**Environment**
- OS + chip: (e.g. Windows 11 / AMD GPU, macOS 15 / M3, Linux / NVIDIA)
- Accelerator: (DirectML / MLX / CUDA / CPU)
- Scubiee version: `scubiee --version`
- IDE / MCP client: (Cursor, Claude Code, Kiro, …)

**Diagnostic bundle** (most useful)
Run and attach the output:
```bash
scubiee diagnose --no-tests --desktop
```
Plus a tail of `~/.scubiee/engine.log` around the failure.

**Logs / screenshots**
Paste any relevant output.
