# map `focus` — multi-language symbol resolution (0.3.146)

## Problem

`map config=focus names=["Sym"]` resolved symbols **only in Python**. For every
other language the tool fell through to the engine's `/v1/outline`, which is
Python-AST-only and replies `{"language_unsupported": true, "note": "outline is
Python AST only"}`. Consequences on a non-Python codebase:

- `focus names=["loginAsync"]` on a TypeScript function → `could not resolve`.
- `focus names=["login"]` → wrongly resolved to a Python `login.py` instead of
  the TS `login.ts`, because the only outlines that ever succeeded were Python.

`find` was unaffected (it uses the semantic vector index), which is why the gap
was easy to miss: find looked fine while focus quietly failed off-Python.

Separately, Python files carrying a leading UTF-8 BOM also failed to outline
(`ast.parse` rejects U+FEFF) in the MCP-local path.

## Fix

New module **`packages/pipeline/map_lang_outline.py`**: a focused, self-contained
tree-sitter outline that reuses the SAME grammars Scubiee already depends on for
graph extraction. It returns the Python-AST outline shape
(`{kind, symbol, line, end_line}`, with `Class.method` nesting) for:

`.py .pyi` (stdlib AST) and, via tree-sitter,
`.js .jsx .mjs .cjs .ts .mts .cts .tsx .go .rs .java .c .h .cpp .cc .cxx .hpp
.hh .rb .cs`.

Wiring in `map_v3_helpers.py`:
- `_outline()` now routes non-Python supported files through
  `map_lang_outline.outline_text`, falling back to the engine `/v1/outline`
  only if the grammar is missing or parsing fails (never worse than before).
- `_resolve_symbol_name()` (the bare-name resolver behind focus) now:
  - greps with language-agnostic definition shapes (keyword-led **and**
    keyword-less `NAME(` / `NAME<` method/type declarations for Java/C/C++/C#),
    then
  - confirms every candidate against the multi-language outline (`_enclosing`),
    and
  - scans candidate-file outlines directly as a second pass.
  This is what makes resolution *correct* across languages rather than relying
  on a lucky keyword grep.
- `_py_outline()` strips a leading BOM before `ast.parse` (the 0.3.146 BOM fix).

### Design properties
- **Graceful degradation.** A missing grammar (`.kt .swift .php .scala .sh` are
  not core deps) or a parse error returns `[]` and focus falls back to grep —
  it never raises.
- **BOM-safe** on every path.
- **Error-tolerant.** Tree-sitter recovers partial symbols from truncated or
  partially-invalid TS/Go/C++ files, so focus still works mid-edit.

## Verification

- `tests/test_map_lang_outline.py` — outline finds the expected symbols in TS,
  TSX, JS, Go, Rust, Java, C#, C++, C, Ruby; BOM-invariance per language;
  unknown-ext and missing-grammar both degrade to `[]`; Python AST + BOM path.
- `tests/test_map_outline_bom.py` — the Python BOM regression.
- End-to-end on a 9-language fixture and on the repo's own `.ts` files:
  `focus` resolves bare names, `Class.method`, and BOM files to the correct
  file; `find` returns the correct multi-language symbols with `Class.method`
  labels. The original failing case (`loginAsync`, `login`) now resolves to the
  right TypeScript file.
- Robustness: malformed/truncated/empty/garbage sources in every language
  produce a sensible partial-or-empty outline with no crash.

## Grammar coverage note

Languages outline via tree-sitter only when their grammar ships as a core
dependency (python, javascript, typescript, go, rust, java, c, cpp, ruby,
c-sharp). Extensions in the map tool's `SOURCE_EXT` without a bundled grammar
(`.kt .swift .php .scala .sh`) resolve via the grep fallback instead; adding
their grammars as dependencies would upgrade them to full tree-sitter outlines
with no further code change.
