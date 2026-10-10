"""Regression: map `focus` must resolve symbols in source files that carry a
leading UTF-8 BOM.

Root cause (fixed in 0.3.146): `_py_outline` read files as plain utf-8, so a
BOM survived as U+FEFF at offset 0. `ast.parse` rejects that with
"invalid non-printable character U+FEFF", `_py_outline` swallowed the
SyntaxError and returned [], and so `_resolve_symbol_name` -> `focus` could not
resolve ANY symbol in a BOM file while `find` (which uses the engine vector
index) still worked. The fix strips a leading BOM before parsing.
"""

from __future__ import annotations

from pathlib import Path

from pipeline import map_v3_helpers as H


def _write(tmp_path: Path, name: str, body: str, *, bom: bool) -> Path:
    p = tmp_path / name
    data = ("\ufeff" if bom else "") + body
    p.write_text(data, encoding="utf-8")
    return p


SAMPLE = (
    '"""Module docstring."""\n'
    "\n"
    "\n"
    "def top_level_func(x):\n"
    "    return x + 1\n"
    "\n"
    "\n"
    "class SampleClass:\n"
    "    def method(self):\n"
    "        return 2\n"
)


def _point_repo_at(tmp_path: Path, monkeypatch) -> None:
    # _py_outline/_resolve_symbol_name resolve paths relative to H.REPO and use
    # mtime-keyed caches; isolate both to the tmp repo for a deterministic test.
    monkeypatch.setattr(H, "REPO", tmp_path)
    monkeypatch.setattr(H, "_FILES", None)
    H._OUTLINE.clear()
    H._LINES.clear()
    H._TEXT.clear()
    H._TEXT_LOWER.clear()


def test_py_outline_handles_leading_bom(tmp_path, monkeypatch):
    _point_repo_at(tmp_path, monkeypatch)
    _write(tmp_path, "with_bom.py", SAMPLE, bom=True)

    syms = H._py_outline("with_bom.py")
    names = {s["symbol"] for s in syms}

    assert "top_level_func" in names, f"BOM file outline missing func: {names}"
    assert "SampleClass" in names, f"BOM file outline missing class: {names}"
    # line numbers must be unchanged by the BOM strip (BOM was a 0-width char on
    # line 1, so `def` is still line 4 / class still line 8).
    by_name = {s["symbol"]: s for s in syms}
    assert by_name["top_level_func"]["line"] == 4
    assert by_name["SampleClass"]["line"] == 8


def test_py_outline_matches_no_bom(tmp_path, monkeypatch):
    # A BOM file and the identical no-BOM file must produce the SAME outline.
    _point_repo_at(tmp_path, monkeypatch)
    _write(tmp_path, "plain.py", SAMPLE, bom=False)
    plain = H._py_outline("plain.py")

    _point_repo_at(tmp_path, monkeypatch)
    _write(tmp_path, "bommed.py", SAMPLE, bom=True)
    bommed = H._py_outline("bommed.py")

    assert [(s["symbol"], s["line"], s["end_line"]) for s in plain] == [
        (s["symbol"], s["line"], s["end_line"]) for s in bommed
    ]


def test_resolve_symbol_name_in_bom_file(tmp_path, monkeypatch):
    _point_repo_at(tmp_path, monkeypatch)
    _write(tmp_path, "mod_with_bom.py", SAMPLE, bom=True)

    res = H._resolve_symbol_name("top_level_func")
    assert res is not None, "focus could not resolve a symbol in a BOM-prefixed file"
    assert res["symbol"] == "top_level_func"
    assert res["file"].endswith("mod_with_bom.py")
    assert res["start"] == 4
