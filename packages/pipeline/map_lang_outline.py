"""Language-agnostic symbol outline for the map tool's `focus` config.

Python files use the stdlib AST (fast, no grammar needed). Every other language
is parsed with its tree-sitter grammar — the SAME grammars Scubiee already
depends on for graph extraction (see graphify/extractors) — so `focus` can
resolve a symbol by name in TypeScript, Go, Rust, Java, C/C++, Ruby, C#, JS/TSX,
etc., not just Python.

Design goals:
- Reliable across every language whose grammar ships as a core dependency.
- Degrade gracefully: a missing grammar or a parse error returns [] (never
  raises), so `focus` falls back to its grep-based resolver instead of breaking.
- BOM-safe: a leading UTF-8 BOM never defeats parsing.
- Output shape identical to the Python AST outline:
  {"kind": "class"|"function"|"method", "symbol": "Name" | "Class.method",
   "line": 1-based start, "end_line": 1-based end}.

This module imports tree-sitter lazily and caches one parser per language, so
importing it is cheap even when no non-Python file is ever outlined.
"""

from __future__ import annotations

import ast
import os
from functools import lru_cache
from typing import Any

# ---------------------------------------------------------------------------
# Language table: extension -> (grammar module, language factory attr, node-type
# sets). Mirrors graphify/extractors/models.LanguageConfig but kept local and
# minimal so the map tool has no hard dependency on the graphify package layout.
# Only languages whose grammar is a CORE dependency (see pyproject.toml) are
# listed; a file whose grammar is absent degrades to the grep fallback.
# ---------------------------------------------------------------------------


class _Lang:
    __slots__ = ("module", "fn", "classes", "functions", "methods_in_class")

    def __init__(self, module, fn, classes, functions, methods_in_class=None):
        self.module = module
        self.fn = fn
        self.classes = frozenset(classes)
        self.functions = frozenset(functions)
        # node types that, inside a class/impl/interface body, are methods
        self.methods_in_class = frozenset(methods_in_class or functions)


# JS/TS share one shape; .tsx needs the JSX-aware grammar factory.
_JS_CLASSES = ("class_declaration",)
_JS_FUNCS = (
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
)
_TS_CLASSES = (
    "class_declaration",
    "abstract_class_declaration",
    "interface_declaration",
    "enum_declaration",
    "type_alias_declaration",
)
_TS_FUNCS = (
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
    "method_signature",
)

_LANGS: dict[str, _Lang] = {
    ".py": _Lang("tree_sitter_python", "language",
                 ("class_definition",), ("function_definition",)),
    ".pyi": _Lang("tree_sitter_python", "language",
                  ("class_definition",), ("function_definition",)),
    ".js": _Lang("tree_sitter_javascript", "language", _JS_CLASSES, _JS_FUNCS),
    ".jsx": _Lang("tree_sitter_javascript", "language", _JS_CLASSES, _JS_FUNCS),
    ".mjs": _Lang("tree_sitter_javascript", "language", _JS_CLASSES, _JS_FUNCS),
    ".cjs": _Lang("tree_sitter_javascript", "language", _JS_CLASSES, _JS_FUNCS),
    ".ts": _Lang("tree_sitter_typescript", "language_typescript", _TS_CLASSES, _TS_FUNCS),
    ".mts": _Lang("tree_sitter_typescript", "language_typescript", _TS_CLASSES, _TS_FUNCS),
    ".cts": _Lang("tree_sitter_typescript", "language_typescript", _TS_CLASSES, _TS_FUNCS),
    ".tsx": _Lang("tree_sitter_typescript", "language_tsx", _TS_CLASSES, _TS_FUNCS),
    ".go": _Lang("tree_sitter_go", "language",
                 ("type_declaration", "type_spec"),
                 ("function_declaration", "method_declaration")),
    ".rs": _Lang("tree_sitter_rust", "language",
                 ("struct_item", "enum_item", "trait_item", "impl_item", "mod_item"),
                 ("function_item",)),
    ".java": _Lang("tree_sitter_java", "language",
                   ("class_declaration", "interface_declaration", "record_declaration",
                    "enum_declaration", "annotation_type_declaration"),
                   ("method_declaration", "constructor_declaration")),
    ".c": _Lang("tree_sitter_c", "language",
                ("struct_specifier", "union_specifier", "enum_specifier"),
                ("function_definition",)),
    ".h": _Lang("tree_sitter_c", "language",
                ("struct_specifier", "union_specifier", "enum_specifier"),
                ("function_definition",)),
    ".cpp": _Lang("tree_sitter_cpp", "language",
                  ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
                  ("function_definition",)),
    ".cc": _Lang("tree_sitter_cpp", "language",
                 ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
                 ("function_definition",)),
    ".cxx": _Lang("tree_sitter_cpp", "language",
                  ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
                  ("function_definition",)),
    ".hpp": _Lang("tree_sitter_cpp", "language",
                  ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
                  ("function_definition",)),
    ".hh": _Lang("tree_sitter_cpp", "language",
                 ("class_specifier", "struct_specifier", "union_specifier", "enum_specifier"),
                 ("function_definition",)),
    ".rb": _Lang("tree_sitter_ruby", "language",
                 ("class", "module"), ("method", "singleton_method")),
    ".cs": _Lang("tree_sitter_c_sharp", "language",
                 ("class_declaration", "interface_declaration", "struct_declaration",
                  "enum_declaration", "record_declaration"),
                 ("method_declaration", "constructor_declaration",
                  "local_function_statement")),
}

# Extensions this module knows how to outline (regardless of whether the grammar
# is importable right now). Used by callers to decide whether to try this path.
SUPPORTED_EXT = frozenset(_LANGS)


def supports(ext: str) -> bool:
    return ext.lower() in _LANGS


# ---------------------------------------------------------------------------
# Grammar loading (lazy, cached). Returns a tree_sitter.Parser or None.
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def _parser_for(ext: str):
    lang = _LANGS.get(ext.lower())
    if lang is None:
        return None
    try:
        import importlib

        from tree_sitter import Language, Parser

        mod = importlib.import_module(lang.module)
        fn = getattr(mod, lang.fn, None)
        if fn is None:
            return None
        ts_lang = Language(fn())
        return Parser(ts_lang)
    except Exception:  # noqa: BLE001 — any import/version problem -> grep fallback
        return None


_IDENT_TYPES = frozenset({
    "identifier", "type_identifier", "field_identifier",
    "constant", "scoped_identifier", "constant_identifier",
})


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _unwrap_c_declarator(node, source: bytes) -> str | None:
    """C/C++ function_definition has no `name` field: the name lives inside the
    `declarator` chain (function_declarator -> ... -> identifier). The `type`
    field is the RETURN type, so we must NOT read it as the name."""
    cur = node.child_by_field_name("declarator")
    for _ in range(8):
        if cur is None:
            return None
        if cur.type in _IDENT_TYPES:
            # a scoped name like Foo::bar -> take the trailing segment
            return _text(cur, source).split("::")[-1]
        if cur.type == "function_declarator":
            cur = cur.child_by_field_name("declarator")
            continue
        # pointer_declarator / reference_declarator / parenthesized wrap a
        # nested `declarator`; descend.
        nxt = cur.child_by_field_name("declarator")
        if nxt is None:
            # last resort: first identifier-ish child
            for ch in cur.children:
                if ch.type in _IDENT_TYPES:
                    return _text(ch, source).split("::")[-1]
            return None
        cur = nxt
    return None


def _name_of(node, source: bytes) -> str | None:
    """Best-effort symbol name for a definition node, across grammars."""
    nn = node.child_by_field_name("name")
    if nn is not None:
        return _text(nn, source).split("::")[-1]
    # C/C++ functions: name is in the declarator chain, never the `type` field.
    if node.type == "function_definition":
        got = _unwrap_c_declarator(node, source)
        if got:
            return got
    # Rust impl blocks: `impl Foo` / `impl Trait for Foo` -> the `type` field is
    # the implemented type, which is the right outline label here.
    tf = node.child_by_field_name("type")
    if tf is not None and tf.type in _IDENT_TYPES:
        return _text(tf, source).split("::")[-1]
    # Go type_declaration wraps a type_spec; C/C++ anonymous structs have none.
    for child in node.children:
        if child.type in _IDENT_TYPES:
            return _text(child, source).split("::")[-1]
    return None


def _go_receiver_type(node, source: bytes) -> str | None:
    """For a Go `method_declaration`, return the receiver type name (the `T` in
    `func (r *T) M()`), so the method is labelled `T.M`."""
    recv = node.child_by_field_name("receiver")
    if recv is None:
        return None
    for ch in recv.children:
        # parameter_declaration -> type is pointer_type/type_identifier
        tnode = ch.child_by_field_name("type") if ch.type == "parameter_declaration" else None
        cur = tnode
        for _ in range(4):
            if cur is None:
                break
            if cur.type == "type_identifier":
                return _text(cur, source)
            # pointer_type wraps the pointee
            nxt = None
            for c in cur.children:
                if c.type in ("type_identifier", "pointer_type", "generic_type"):
                    nxt = c
                    break
            cur = nxt
    return None


def _body_of(node):
    b = node.child_by_field_name("body")
    if b is not None:
        return b
    # C/C++/C#/Java use these body container types
    for child in node.children:
        if child.type in ("declaration_list", "field_declaration_list",
                          "compound_statement", "class_body", "enum_body",
                          "interface_body", "block", "struct_body"):
            return child
    return None


def _ts_outline(ext: str, source_text: str) -> list[dict[str, Any]]:
    parser = _parser_for(ext)
    if parser is None:
        return []
    try:
        source = source_text.encode("utf-8")
        tree = parser.parse(source)
    except Exception:  # noqa: BLE001
        return []
    lang = _LANGS[ext.lower()]
    out: list[dict[str, Any]] = []

    def emit(node, name: str, kind: str):
        out.append({
            "kind": kind,
            "symbol": name,
            "line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
        })

    def walk(node, prefix: str, in_type: bool):
        for child in node.children:
            t = child.type
            is_class = t in lang.classes
            is_func = t in lang.functions
            if is_class:
                name = _name_of(child, source)
                if name:
                    emit(child, f"{prefix}{name}", "class")
                    body = _body_of(child)
                    if body is not None:
                        walk(body, f"{prefix}{name}.", True)
                    else:
                        walk(child, f"{prefix}{name}.", True)
                else:
                    walk(child, prefix, in_type)
            elif is_func:
                name = _name_of(child, source)
                if name:
                    kind = "method" if in_type else "function"
                    # Go/Rust-style top-level methods carry a receiver; label
                    # them Type.method so focus can find them either way.
                    recv = _go_receiver_type(child, source) if t == "method_declaration" else None
                    label = f"{recv}.{name}" if recv else f"{prefix}{name}"
                    if recv:
                        kind = "method"
                    emit(child, label, kind)
                    # nested functions/classes inside a function body are rare in
                    # the target languages and add noise; stop here.
                else:
                    walk(child, prefix, in_type)
            else:
                # descend through namespaces/wrappers (Go type_declaration,
                # C# namespace, Rust mod handled via classes above) to reach defs
                walk(child, prefix, in_type)

    walk(tree.root_node, "", False)
    out.sort(key=lambda s: (s["line"], s["symbol"]))
    return out


def _py_outline_text(source_text: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(source_text.lstrip("\ufeff"))
    except (SyntaxError, ValueError):
        return []
    out: list[dict[str, Any]] = []

    def walk(node, prefix: str, in_class: bool):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{ch.name}"
                kind = "class" if isinstance(ch, ast.ClassDef) else ("method" if in_class else "function")
                start = min([ch.lineno] + [d.lineno for d in getattr(ch, "decorator_list", [])])
                out.append({"kind": kind, "symbol": name, "line": start,
                            "end_line": getattr(ch, "end_lineno", ch.lineno) or ch.lineno})
                if isinstance(ch, ast.ClassDef):
                    walk(ch, name + ".", True)

    walk(tree, "", False)
    out.sort(key=lambda s: s["line"])
    return out


def outline_text(ext: str, source_text: str) -> list[dict[str, Any]]:
    """Outline from already-read source text (BOM already present or not).

    Python goes through the stdlib AST; everything else through tree-sitter.
    Returns [] (never raises) for unknown extensions, missing grammars, or
    parse errors so the caller can fall back.
    """
    e = ext.lower()
    if e in (".py", ".pyi"):
        return _py_outline_text(source_text)
    if e in _LANGS:
        # strip a leading BOM so byte offsets/line math stay consistent with the
        # on-disk text the span reader uses (it also strips the BOM).
        return _ts_outline(e, source_text.lstrip("\ufeff"))
    return []
