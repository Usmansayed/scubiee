"""Fast source-level release checks that must not require model or daemon setup."""

from __future__ import annotations

import py_compile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_modules_compile() -> None:
    """Every shipped pipeline module must be importable before any runtime gate."""
    failures: list[str] = []
    for source in sorted((ROOT / "packages" / "pipeline").glob("*.py")):
        try:
            py_compile.compile(str(source), doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(str(exc))
    assert not failures, "\n".join(failures)
