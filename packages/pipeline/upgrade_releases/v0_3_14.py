"""Release 0.3.14 — doctor expected-binary path on Windows venv/uv layouts."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release("0.3.14", notes="Fix expected_scubiee_exe double-Scripts path in doctor")
class Release_0_3_14:
    pass
