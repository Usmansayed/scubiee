"""Tests for SEIR caps + span extraction (chunk units)."""

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


def _fixture(tmp_path: Path) -> Path:
    p = tmp_path / "m.py"
    p.write_text(
        "def login(email, password):\n"
        "    return 1\n\n"
        "class A:\n"
        "    def f(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    return tmp_path


def test_spans_function_unit(tmp_path: Path):
    root = _fixture(tmp_path)
    spans = iter_python_spans(root, chunk_unit="function")
    names = {s.symbol for s in spans}
    assert "login" in names
    assert "A" in names
    assert "A.f" in names


def test_spans_class_unit_folds_methods(tmp_path: Path):
    root = _fixture(tmp_path)
    spans = iter_python_spans(root, chunk_unit="class")
    names = {s.symbol for s in spans}
    assert "login" in names
    assert "A" in names
    assert "A.f" not in names
    a = next(s for s in spans if s.symbol == "A")
    assert "def f" in a.source


def test_spans_file_unit_one_per_file(tmp_path: Path):
    root = _fixture(tmp_path)
    spans = iter_python_spans(root, chunk_unit="file")
    assert len(spans) == 1
    assert spans[0].node_kind == "file"
    assert "def login" in spans[0].source
