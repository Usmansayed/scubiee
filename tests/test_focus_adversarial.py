"""Adversarial focus inputs — found during a bug-bounty pass.

Two real bugs fixed here:
- `focus` could not resolve a symbol whose name has a Unicode letter (valid in
  Python/Go: αβ, École) or `$` (ubiquitous in JS/TS: RxJS `data$`, jQuery `$el`),
  because the resolver's ASCII-only identifier gate rejected them before search.
- `focus names=["file:a-b"]` (an explicit line RANGE) located a valid span but
  was rejected because the resolver required a non-None enclosing symbol.

Plus: hostile targets (path traversal, control chars, huge names, emoji) must
degrade to a clean "could not resolve", never crash or read outside the repo.
"""

from __future__ import annotations

import pathlib

import pytest

from pipeline import map_v3_helpers as H
from pipeline import map_v3_server as S


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "REPO", tmp_path)
    monkeypatch.setattr(H, "_FILES", None)
    H._OUTLINE.clear(); H._LINES.clear(); H._TEXT.clear()
    try:
        H._GREP_SCOPE_FILES.clear()
    except Exception:
        pass
    monkeypatch.setattr(H, "_search", lambda *a, **k: [])  # hermetic
    (tmp_path / "uni.py").write_text(
        "def \u03b1\u03b2(x):\n    return x\n\n\nclass \u00c9cole:\n"
        "    def m\u00e9thode(self):\n        return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dollar.js").write_text(
        "export function $dollar(x) { return x; }\n"
        "export const data$ = () => 1;\n"
        "class A$B {\n  m$() { return 2; }\n}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_resolves_unicode_identifiers(repo):
    for nm in ("\u03b1\u03b2", "\u00c9cole", "m\u00e9thode"):
        r = H._resolve_symbol_name(nm)
        assert r is not None, f"unicode identifier {nm!r} must resolve"


def test_resolves_dollar_identifiers(repo):
    for nm in ("$dollar", "data$", "A$B", "m$"):
        r = H._resolve_symbol_name(nm)
        assert r is not None, f"$ identifier {nm!r} must resolve"


def test_focus_resolves_line_range_target(repo):
    out = S.cfg_focus({"names": ["uni.py:1-2"]})
    assert "could not resolve" not in out, "a valid file:a-b range must resolve"
    # body lines are returned
    body = [ln for ln in out.splitlines() if ln.strip()[:1].isdigit()]
    assert body, "range focus should return numbered body lines"


def test_focus_single_line_target(repo):
    out = S.cfg_focus({"names": ["uni.py:5"]})
    assert "could not resolve" not in out


@pytest.mark.parametrize("bad", [
    "../../../etc/passwd",
    "../../../../etc/passwd::root",
    "\x00\x01\x02",
    "::::::",
    "a::b::c::d",
    "\U0001f525\U0001f525",          # emoji
    "   ",
    "x" * 5000,
])
def test_hostile_targets_degrade_not_crash(repo, bad):
    # must return a string (handled), never raise, never resolve to a real file
    out = S.cfg_focus({"names": [bad]})
    assert isinstance(out, str)
    assert "could not resolve" in out or "error" in out.lower()


def test_junk_still_returns_none(repo):
    for junk in ("123abc", "!!!", "", "   "):
        assert H._resolve_symbol_name(junk) is None


def test_noncode_spans_survives_null_bytes(tmp_path, monkeypatch):
    # A source file containing NUL bytes made the C tokenizer raise a SystemError
    # that escaped the guard and crashed find for ANY query whose results touched
    # the file. _noncode_spans must degrade to [] spans, never raise.
    monkeypatch.setattr(H, "REPO", tmp_path)
    H._NONCODE.clear(); H._LINES.clear(); H._TEXT.clear()
    (tmp_path / "nul.py").write_bytes(b"def before():\n    pass\n\x00\x00\ndef after():\n    pass\n")
    spans = H._noncode_spans("nul.py")  # must not raise
    assert isinstance(spans, dict)
    # _code_text (what find calls) must also survive
    txt = H._code_text("nul.py", 1, 5)
    assert isinstance(txt, str)


def test_find_survives_regex_metachar_queries(repo):
    # Natural-language queries with regex metachars / SQL / parens must not crash
    # find (they are not patterns; find is semantic).
    for q in ["SELECT * FROM t; DROP TABLE u;--", "(((((", ".*.*.*", "[a-z]+$", "\\n\\t"]:
        out = S.cfg_find({"query": q})
        assert isinstance(out, str)
