"""Bare-name resolution recall + robustness for map focus.

Regressions found by running real repos through focus:
- a symbol defined only in a test file must still resolve (the resolver used to
  hard-filter to kind=="code" and drop every test-only symbol);
- definition shapes the keyword grep can't match (C
  `struct __attribute__((packed)) Name`) must resolve via the outline fallback;
- resolution must return None (never raise) when the engine is unreachable,
  since focus runs it and the grep+outline passes are engine-free.
"""

from __future__ import annotations

import pathlib

import pytest

from pipeline import map_v3_helpers as H


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "REPO", tmp_path)
    monkeypatch.setattr(H, "_FILES", None)
    H._OUTLINE.clear()
    H._LINES.clear()
    H._TEXT.clear()
    try:
        H._GREP_SCOPE_FILES.clear()
    except Exception:
        pass
    # make the engine-backed semantic fallback a no-op so tests are hermetic
    monkeypatch.setattr(H, "_search", lambda *a, **k: [])
    return tmp_path


def _w(root: pathlib.Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_resolves_symbol_defined_only_in_tests(repo):
    _w(repo, "src/app.py", "def real():\n    return 1\n")
    _w(repo, "tests/test_app.py",
       "import unittest\nclass CacheTest(unittest.TestCase):\n    def test_x(self):\n        pass\n")
    r = H._resolve_symbol_name("CacheTest")
    assert r is not None, "test-only class must resolve by bare name"
    assert r["file"].endswith("tests/test_app.py")
    assert r["symbol"] == "CacheTest"


def test_prefers_code_over_tests_when_both_define(repo):
    _w(repo, "src/thing.py", "class Thing:\n    pass\n")
    _w(repo, "tests/test_thing.py", "class Thing:\n    pass\n")
    r = H._resolve_symbol_name("Thing")
    assert r is not None
    assert r["file"].endswith("src/thing.py"), "code definition should win over the test one"


def test_resolves_c_attribute_wrapped_struct(repo):
    # the keyword grep pattern can't match `struct <attr> Name`; the plain
    # outline fallback must still find it.
    _w(repo, "sds.h",
       "struct __attribute__ ((__packed__)) sdshdr5 {\n"
       "    unsigned char flags;\n"
       "    char buf[];\n"
       "};\n")
    r = H._resolve_symbol_name("sdshdr5")
    assert r is not None, "attribute-wrapped C struct must resolve"
    assert r["symbol"] == "sdshdr5"


def test_junk_name_stays_none(repo):
    _w(repo, "src/app.py", "def real():\n    return 1\n")
    for junk in ("zzzNoSuchSymbol", "notrealfn", "123abc", ""):
        assert H._resolve_symbol_name(junk) is None, f"{junk!r} must not resolve"


def test_resolution_never_raises_when_engine_down(repo, monkeypatch):
    # make the semantic fallback blow up like a refused HTTP connection would
    def boom(*a, **k):
        raise RuntimeError("engine /v1/search failed: Connection refused")

    monkeypatch.setattr(H, "_search", boom)
    _w(repo, "src/app.py", "def only_defined_here():\n    return 1\n")
    # a name that the grep+outline passes won't find -> would reach _search
    assert H._resolve_symbol_name("totally_absent_name") is None
    # and a real one still resolves without touching _search
    r = H._resolve_symbol_name("only_defined_here")
    assert r is not None and r["symbol"] == "only_defined_here"
