"""Multi-language outline + focus resolution.

`map config=focus` must resolve a symbol by name in EVERY language whose
tree-sitter grammar is a core dependency — not just Python. Before this,
non-Python files went to the engine's /v1/outline, which is Python-AST-only and
returns `language_unsupported`, so focus silently failed for TS/JS/Go/Rust/
Java/C/C++/Ruby/C#.

These tests drive the standalone outline (pipeline.map_lang_outline) directly so
they do not need a running engine. A language whose grammar is not importable is
skipped (not failed), because grammars outside the core set are optional.
"""

from __future__ import annotations

import importlib

import pytest

from pipeline import map_lang_outline as M


def _has_grammar(ext: str) -> bool:
    lang = M._LANGS.get(ext)
    if lang is None:
        return False
    try:
        importlib.import_module(lang.module)
        return True
    except Exception:  # noqa: BLE001
        return False


# (ext, source, expected symbol leaf names that MUST appear)
CASES = [
    (".ts",
     "export function login(u: string): string { return u; }\n"
     "export class AuthService {\n  verify(t: string): boolean { return t.length > 0; }\n}\n",
     {"login", "AuthService", "verify"}),
    (".tsx",
     "export function View() { return null; }\n"
     "export class Panel { render() { return null; } }\n",
     {"View", "Panel", "render"}),
    (".js",
     "export function login(u) { return u; }\n"
     "export class AuthService { verify(t) { return !!t; } }\n",
     {"login", "AuthService", "verify"}),
    (".go",
     "package main\n"
     "func Login(u string) string { return u }\n"
     "type AuthService struct{ n string }\n"
     "func (a *AuthService) Verify(t string) bool { return len(t) > 0 }\n",
     {"Login", "AuthService", "Verify"}),
    (".rs",
     "pub fn login(u: &str) -> String { u.to_string() }\n"
     "pub struct AuthService { n: String }\n"
     "impl AuthService { pub fn verify(&self, t: &str) -> bool { t.len() > 0 } }\n",
     {"login", "AuthService", "verify"}),
    (".java",
     "public class AuthService {\n"
     "  public String login(String u) { return u; }\n"
     "  public boolean verify(String t) { return t.length() > 0; }\n}\n",
     {"AuthService", "login", "verify"}),
    (".cs",
     "namespace App {\n  public class AuthService {\n"
     "    public string Login(string u) { return u; }\n"
     "    public bool Verify(string t) { return t.Length > 0; }\n  }\n}\n",
     {"AuthService", "Login", "Verify"}),
    (".cpp",
     "#include <string>\n"
     "std::string login(const std::string& u) { return u; }\n"
     "class AuthService {\npublic:\n  bool verify(const std::string& t) { return t.size() > 0; }\n};\n",
     {"login", "AuthService", "verify"}),
    (".c",
     "int add(int a, int b) { return a + b; }\n"
     "struct Point { int x; int y; };\n",
     {"add", "Point"}),
    (".rb",
     "class AuthService\n  def login(u)\n    u\n  end\n  def verify(t)\n    t.length > 0\n  end\nend\n",
     {"AuthService", "login", "verify"}),
]


@pytest.mark.parametrize("ext,src,expected", CASES, ids=[c[0] for c in CASES])
def test_outline_finds_symbols(ext, src, expected):
    if not _has_grammar(ext):
        pytest.skip(f"grammar for {ext} not installed")
    syms = M.outline_text(ext, src)
    leaves = {s["symbol"].split(".")[-1] for s in syms}
    missing = expected - leaves
    assert not missing, f"{ext}: outline missing {missing}; got {leaves}"
    # every symbol has a sane 1-based line range
    for s in syms:
        assert s["line"] >= 1
        assert s["end_line"] >= s["line"]
        assert s["kind"] in ("class", "function", "method")


ARROW_CASES = [
    (".ts",
     "export const makeHelper = (n: number) => n + 1;\n"
     "const plain = function (x) { return x; };\n"
     "export function reg() { return 1; }\n"
     "export class C {\n  field = (x) => x;\n  method() { return 2; }\n}\n",
     {"makeHelper", "plain", "reg", "C", "field", "method"}),
    (".tsx",
     "export const Panel = () => null;\n"
     "export function Other() { return null; }\n",
     {"Panel", "Other"}),
    (".js",
     "export const h = (n) => n + 1;\n"
     "const g = function () { return 0; };\n",
     {"h", "g"}),
]


@pytest.mark.parametrize("ext,src,expected", ARROW_CASES, ids=[c[0] for c in ARROW_CASES])
def test_outline_finds_arrow_and_function_expressions(ext, src, expected):
    """const f = () => ... / const f = function(){} / class-field arrows are the
    dominant function form in modern JS/TS and must be focus-resolvable."""
    if not _has_grammar(ext):
        pytest.skip(f"grammar for {ext} not installed")
    syms = M.outline_text(ext, src)
    leaves = {s["symbol"].split(".")[-1] for s in syms}
    missing = expected - leaves
    assert not missing, f"{ext}: arrow/function-expr outline missing {missing}; got {leaves}"


@pytest.mark.parametrize("ext", [".ts", ".go", ".rs", ".java", ".rb"])
def test_outline_handles_bom(ext):
    if not _has_grammar(ext):
        pytest.skip(f"grammar for {ext} not installed")
    bodies = {
        ".ts": "export function f(x: number): number { return x; }\n",
        ".go": "package main\nfunc F() int { return 1 }\n",
        ".rs": "pub fn f() -> i32 { 1 }\n",
        ".java": "public class K { public int f() { return 1; } }\n",
        ".rb": "def f\n  1\nend\n",
    }
    plain = M.outline_text(ext, bodies[ext])
    bommed = M.outline_text(ext, "\ufeff" + bodies[ext])
    assert plain, f"{ext}: no symbols from plain source"
    assert [s["symbol"] for s in plain] == [s["symbol"] for s in bommed], (
        f"{ext}: BOM changed the outline"
    )


def test_unknown_ext_returns_empty_not_error():
    # a format we don't outline must degrade to [], never raise
    assert M.outline_text(".zig", "fn main() void {}") == []
    assert M.outline_text(".txt", "hello world") == []


def test_missing_grammar_degrades_gracefully(monkeypatch):
    # if a grammar import fails, outline returns [] (caller then uses the grep /
    # engine fallback) rather than raising.
    M._parser_for.cache_clear()
    monkeypatch.setattr(
        M, "_parser_for", lambda ext: None
    )
    assert M.outline_text(".go", "func F() {}") == []


def test_python_path_uses_ast_and_strips_bom():
    src = "def top():\n    return 1\n\n\nclass C:\n    def m(self):\n        return 2\n"
    plain = M.outline_text(".py", src)
    bommed = M.outline_text(".py", "\ufeff" + src)
    leaves = {s["symbol"].split(".")[-1] for s in plain}
    assert {"top", "C", "m"} <= leaves
    assert [s["symbol"] for s in plain] == [s["symbol"] for s in bommed]
