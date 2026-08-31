"""Guard against polluted ``CTX_HOME`` in production CLI/MCP entry points."""

from __future__ import annotations

import os
import sys
from typing import Any, TextIO

_POLLUTION_TOKENS = (
    "/temp/",
    "/tmp/",
    "\\temp\\",
    "\\tmp\\",
    "bridge_live_test",
    "pytest-of-",
    "scubiee-test-home",  # conftest isolation dir name (still allowed via test bypass)
)


def allows_test_ctx_home() -> bool:
    if os.environ.get("CTX_ALLOW_TEST_HOME", "").strip() in {"1", "true", "yes"}:
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules and bool(os.environ.get("PYTEST_CURRENT_TEST"))


def ctx_home_pollution_reason(raw: str) -> str | None:
    """Return a short reason when *raw* looks like a temp/test home, else ``None``."""
    text = raw.strip()
    if not text:
        return None
    lower = text.replace("\\", "/").lower()
    for token in _POLLUTION_TOKENS:
        if token.replace("\\", "/") in lower:
            return f"matches {token!r}"
    return None


def validate_ctx_home() -> dict[str, Any]:
    raw = (os.environ.get("CTX_HOME") or "").strip()
    if not raw:
        return {"ok": True}
    if allows_test_ctx_home():
        return {"ok": True, "ctx_home": raw, "test_bypass": True}
    reason = ctx_home_pollution_reason(raw)
    if reason:
        return {
            "ok": False,
            "error": "ctx_home_polluted",
            "ctx_home": raw,
            "reason": reason,
            "hint": (
                "Unset CTX_HOME (use default ~/.scubiee) or run "
                "`scubiee connect --<tool>` again from a clean shell."
            ),
        }
    return {"ok": True, "ctx_home": raw}


def format_ctx_home_error(report: dict[str, Any]) -> str:
    return (
        f"[scubiee] refusing to start: CTX_HOME={report.get('ctx_home')!r} "
        f"looks like a test/temp path ({report.get('reason')}). "
        f"{report.get('hint', '')}"
    )


def enforce_ctx_home_or_exit(*, stream: TextIO | None = None) -> None:
    """Exit the process when ``CTX_HOME`` is a polluted temp path (production)."""
    report = validate_ctx_home()
    if report.get("ok"):
        return
    out = stream if stream is not None else sys.stderr
    out.write(format_ctx_home_error(report) + "\n")
    out.flush()
    raise SystemExit(1)


def warn_ctx_home_pollution(*, stream: TextIO | None = None) -> None:
    """Warn on stderr when ``CTX_HOME`` looks polluted (non-fatal)."""
    report = validate_ctx_home()
    if report.get("ok") or report.get("test_bypass"):
        return
    out = stream if stream is not None else sys.stderr
    out.write(format_ctx_home_error(report) + "\n")
    out.flush()
