"""Indexable-extension coverage.

The index extension gate (merkle.DEFAULT_EXTENSIONS, shared by paths.index_rel_ok)
decides which files enter the corpus at all. Common C++ source extensions
(.cc/.cxx) and Node ES-module/CommonJS extensions (.mjs/.cjs/.mts/.cts) route to
real graphify extractors with bundled grammars, but were missing from the gate —
so those files were silently never indexed and both find and focus were blind to
them. These tests pin the coverage so the regression can't return.
"""

from __future__ import annotations

from pipeline.merkle import DEFAULT_EXTENSIONS


def test_common_cpp_source_extensions_are_indexable():
    for ext in (".cpp", ".cc", ".cxx", ".c", ".h", ".hpp"):
        assert ext in DEFAULT_EXTENSIONS, f"{ext} C/C++ source must be indexable"


def test_node_module_extensions_are_indexable():
    for ext in (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"):
        assert ext in DEFAULT_EXTENSIONS, f"{ext} JS/TS module must be indexable"


def test_index_gate_matches_extensions(tmp_path):
    # The gate used by the real indexer must accept these extensions.
    from pipeline.ignore import load_scubiee_ignore
    from pipeline.paths import index_rel_ok

    rules = load_scubiee_ignore(tmp_path)
    for name in ("a.cc", "b.cxx", "c.mjs", "d.cjs", "e.mts", "f.cts", "g.cpp", "h.py"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
        assert index_rel_ok(tmp_path, name, rules=rules), f"{name} should pass the index gate"


def test_every_indexable_ext_has_a_graphify_extractor():
    # Guard the invariant that makes adding an extension safe: it must route to a
    # real extractor, else indexing produces chunks a parser can't structure.
    from graphify.extract import _DISPATCH

    for ext in DEFAULT_EXTENSIONS:
        if ext == ".md":
            continue  # markdown is a doc, handled separately
        assert _DISPATCH.get(ext) is not None, (
            f"{ext} is marked indexable but has no graphify extractor"
        )
