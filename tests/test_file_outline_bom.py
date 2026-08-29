"""BOM-prefixed Python files must still produce AST outlines."""

from __future__ import annotations

from pathlib import Path

from pipeline.capability import file_outline, read_python_source


def test_read_python_source_strips_bom(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    f.write_bytes(b"\xef\xbb\xbef\nx = 1\n")
    text = read_python_source(f)
    assert not text.startswith("\ufeff")
    assert "x = 1" in text


def test_file_outline_works_with_bom(tmp_path: Path) -> None:
    f = tmp_path / "pkg" / "mod.py"
    f.parent.mkdir(parents=True)
    f.write_bytes(
        b"\xef\xbb\xbfclass Foo:\n    def bar(self):\n        return 1\n",
    )
    symbols = file_outline(tmp_path, "pkg/mod.py")
    names = {s.get("symbol") for s in symbols}
    assert "Foo" in names
    assert "Foo.bar" in names
