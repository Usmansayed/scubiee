"""Tests for SEIR caps + span extraction."""

from __future__ import annotations

from pathlib import Path

from seir.caps import estimate_tokens, truncate
from seir.spans import iter_python_spans


def test_truncate_prefers_head():
    assert truncate("abcdef", 4) == "abc…"
    assert len(truncate("x" * 100, 512)) <= 512
    assert truncate("short", 512) == "short"


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1


def test_spans_from_fixture(tmp_path: Path):
    p = tmp_path / "m.py"
    p.write_text(
        "def login(email, password):\n"
        "    return 1\n\n"
        "class A:\n"
        "    def f(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    spans = iter_python_spans(tmp_path)
    names = {s.symbol for s in spans}
    assert "login" in names
    assert "A" in names
    assert "A.f" in names
    login = next(s for s in spans if s.symbol == "login")
    assert "def login" in login.source
    assert login.start_line == 1
