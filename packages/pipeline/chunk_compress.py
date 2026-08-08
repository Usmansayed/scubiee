"""Pre-embed chunk compression (after enrichment, before CodeRank).

Deterministic models — no LLM:
  1. skeleton   — AST structural skeleton
  2. card       — retrieval card (metadata + intent, body only if budget left)
  3. importance — static importance scorer fill-to-budget
  4. mix        — card-labeled core + importance body fill (same max_chars)

Hard cap: 512 characters (default). Prefer 350–450 when content allows.

Budget-allocation presets (fixed total, different spend):
  budget_a — identity-heavy (40% meta, 30% symbols, 20% APIs, 10% body)
  budget_b — balanced     (25% meta, 25% symbols, 20% APIs, 30% body)
  budget_c — body-heavy   (20% meta, 20% symbols, 10% APIs, 50% body)

Body remainder always prefers rare identifiers / distinctive calls over
first-N body characters.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Callable

MAX_CHARS_DEFAULT = 512
TARGET_SOFT = 450  # prefer staying under this when possible
TARGET_MIN = 350

_META_SEP = "--------------------------------"
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")

# Low-importance tokens for Model 3
_STOP_KW = frozenset(
    {
        "const",
        "let",
        "var",
        "if",
        "else",
        "elif",
        "for",
        "while",
        "with",
        "as",
        "pass",
        "break",
        "continue",
        "try",
        "except",
        "finally",
        "raise",
        "assert",
        "print",
        "log",
        "logger",
        "debug",
        "info",
        "warning",
        "error",
        "true",
        "false",
        "none",
        "null",
        "undefined",
        "return",
        "from",
        "import",
        "def",
        "class",
        "async",
        "await",
        "and",
        "or",
        "not",
        "in",
        "is",
        "self",
        "cls",
    }
)


@dataclass
class CompressResult:
    mode: str
    text: str
    original_chars: int
    compressed_chars: int

    @property
    def ratio(self) -> float:
        if self.original_chars <= 0:
            return 1.0
        return self.compressed_chars / self.original_chars


def split_enriched(enriched: str) -> tuple[str, str]:
    """Split metadata header from body (enrichment separator)."""
    if _META_SEP in enriched:
        head, _, tail = enriched.partition(_META_SEP)
        return head.rstrip() + "\n", tail.lstrip("\n")
    # fallback: treat as body-only
    return "", enriched


def _trim_to_budget(text: str, budget: int) -> str:
    """Intelligent trim: prefer cutting at newline / sentence / identifier boundary."""
    text = text.strip()
    if len(text) <= budget:
        return text
    cut = text[:budget]
    # try last newline in last 20% of budget
    window = cut[int(budget * 0.8) :]
    nl = window.rfind("\n")
    if nl >= 0:
        return cut[: int(budget * 0.8) + nl].rstrip()
    sp = cut.rfind(" ")
    if sp > budget * 0.7:
        return cut[:sp].rstrip()
    return cut.rstrip()


def _fit_budget(parts: list[str], budget: int, *, soft: int = TARGET_SOFT) -> str:
    """Greedy pack parts; stop near soft target if already informative."""
    out: list[str] = []
    n = 0
    for p in parts:
        p = p.strip()
        if not p:
            continue
        add = len(p) + (1 if out else 0)
        if n + add > budget:
            remain = budget - n - (1 if out else 0)
            if remain >= 24:
                out.append(_trim_to_budget(p, remain))
            break
        out.append(p)
        n += add
        if n >= soft and len(out) >= 3:
            # enough signal — don't pack forever
            break
    return _trim_to_budget("\n".join(out), budget)


def _parse_meta_lines(header: str) -> dict[str, list[str] | str]:
    meta: dict[str, list[str] | str] = {
        "repository": "",
        "module": "",
        "folder": "",
        "file": "",
        "functions": [],
        "imports": [],
        "exports": [],
        "related": [],
        "dependents": [],
    }
    section = None
    for raw in header.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Repository:"):
            meta["repository"] = line.split(":", 1)[1].strip()
        elif line.startswith("Module:"):
            meta["module"] = line.split(":", 1)[1].strip()
        elif line.startswith("Folder:"):
            meta["folder"] = line.split(":", 1)[1].strip()
        elif line.startswith("File:"):
            meta["file"] = line.split(":", 1)[1].strip()
        elif line == "Functions:":
            section = "functions"
        elif line == "Imports:":
            section = "imports"
        elif line == "Exports:":
            section = "exports"
        elif line.startswith("Graph Context"):
            section = None
        elif line.startswith("Related Files"):
            section = "related"
        elif line.startswith("Immediate Dependents"):
            section = "dependents"
        elif line.startswith("- Parent Folder"):
            continue
        elif line.startswith("- ") and section:
            val = line[2:].strip()
            if val and val != "(none)":
                lst = meta[section]
                assert isinstance(lst, list)
                lst.append(val)
    return meta


def _docstring_from_body(body: str) -> str:
    m = re.search(r'^\s*[ruRU]?("""|\'\'\')(.*?)\1', body, re.DOTALL)
    if m:
        return " ".join(m.group(2).split())[:200]
    # # comments at top
    comments = []
    for line in body.splitlines()[:12]:
        s = line.strip()
        if s.startswith("#"):
            comments.append(s.lstrip("# ").strip())
        elif s and not s.startswith("def ") and not s.startswith("class ") and not s.startswith("@"):
            break
    return " ".join(comments)[:200]


def _signatures_and_calls(body: str) -> tuple[list[str], list[str], list[str]]:
    """Return (signatures, api_calls, type_names) via AST when possible."""
    sigs: list[str] = []
    calls: list[str] = []
    types: list[str] = []
    try:
        tree = ast.parse(body)
    except SyntaxError:
        # regex fallback
        for m in re.finditer(
            r"^(async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)(\s*->\s*([^:]+))?:",
            body,
            re.M,
        ):
            ret = f" -> {m.group(5).strip()}" if m.group(5) else ""
            sigs.append(f"def {m.group(2)}({m.group(3).strip()}){ret}")
        for m in re.finditer(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(\([^)]*\))?:", body, re.M):
            sigs.append(f"class {m.group(1)}{m.group(2) or ''}")
        calls = list(dict.fromkeys(_CALL.findall(body)))[:24]
        return sigs, calls, types

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ast.unparse(node.args) if hasattr(ast, "unparse") else ""
            ret = ""
            if node.returns is not None and hasattr(ast, "unparse"):
                ret = f" -> {ast.unparse(node.returns)}"
                types.append(ast.unparse(node.returns))
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            sigs.append(f"{prefix} {node.name}({args}){ret}")
        elif isinstance(node, ast.ClassDef):
            bases = ""
            if node.bases and hasattr(ast, "unparse"):
                bases = "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
            sigs.append(f"class {node.name}{bases}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)
        if isinstance(node, ast.arg) and node.annotation is not None and hasattr(ast, "unparse"):
            types.append(ast.unparse(node.annotation))
    # unique preserve
    calls = list(dict.fromkeys(calls))[:32]
    types = list(dict.fromkeys(types))[:16]
    return sigs, calls, types


def _skeleton_body(body: str) -> str:
    """Keep structure: defs/classes/docstrings/imports/decorators; drop impl bodies."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        # keep imports + def/class lines + docstring-ish
        keep: list[str] = []
        for line in body.splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ", "def ", "class ", "async def ", "@")):
                keep.append(line.rstrip()[:120])
            elif s.startswith(('"""', "'''", "#")):
                keep.append(line.rstrip()[:120])
        return "\n".join(keep)

    out_lines: list[str] = []

    def emit_doc(node: ast.AST) -> None:
        doc = ast.get_docstring(node)
        if doc:
            one = " ".join(doc.split())[:160]
            out_lines.append(f'"""{one}"""')

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out_lines.append(ast.unparse(node) if hasattr(ast, "unparse") else "import …")
        elif isinstance(node, ast.ClassDef):
            bases = ""
            if node.bases and hasattr(ast, "unparse"):
                bases = "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
            out_lines.append(f"class {node.name}{bases}:")
            emit_doc(node)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = ast.unparse(item.args) if hasattr(ast, "unparse") else "..."
                    ret = ""
                    if item.returns is not None and hasattr(ast, "unparse"):
                        ret = f" -> {ast.unparse(item.returns)}"
                    pref = "async def" if isinstance(item, ast.AsyncFunctionDef) else "def"
                    out_lines.append(f"    {pref} {item.name}({args}){ret}: ...")
                    emit_doc(item)
                elif isinstance(item, ast.AnnAssign) and hasattr(ast, "unparse"):
                    out_lines.append(f"    {ast.unparse(item)}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
            ret = ""
            if node.returns is not None and hasattr(ast, "unparse"):
                ret = f" -> {ast.unparse(node.returns)}"
            pref = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            out_lines.append(f"{pref} {node.name}({args}){ret}: ...")
            emit_doc(node)
            # surface notable calls in body (API hints) without full impl
            _, calls, _ = _signatures_and_calls(ast.unparse(node) if hasattr(ast, "unparse") else "")
            # cheaper: walk node
            api = []
            for n in ast.walk(node):
                if isinstance(n, ast.Call):
                    if isinstance(n.func, ast.Name) and n.func.id not in _STOP_KW:
                        api.append(n.func.id)
                    elif isinstance(n.func, ast.Attribute):
                        api.append(n.func.attr)
            api = list(dict.fromkeys(api))[:8]
            if api:
                out_lines.append("    # calls: " + ", ".join(api))
        elif isinstance(node, ast.Assign) and hasattr(ast, "unparse"):
            # keep module-level constants / exports only (short)
            src = ast.unparse(node)
            if len(src) < 80 and not any(x in src for x in ("logger", "logging")):
                out_lines.append(src)

    return "\n".join(out_lines)


def compress_skeleton(enriched: str, *, max_chars: int = MAX_CHARS_DEFAULT) -> CompressResult:
    header, body = split_enriched(enriched)
    meta = _parse_meta_lines(header)
    skel = _skeleton_body(body)
    parts = [
        f"File: {meta.get('file') or ''}",
        f"Module: {meta.get('module') or ''}",
    ]
    fns = meta.get("functions") or []
    if isinstance(fns, list) and fns:
        parts.append("Functions: " + ", ".join(fns[:8]))
    imps = meta.get("imports") or []
    if isinstance(imps, list) and imps:
        parts.append("Imports: " + ", ".join(imps[:10]))
    exps = meta.get("exports") or []
    if isinstance(exps, list) and exps:
        parts.append("Exports: " + ", ".join(exps[:8]))
    deps = meta.get("dependents") or []
    if isinstance(deps, list) and deps:
        parts.append("Dependents: " + ", ".join(deps[:6]))
    parts.append("Skeleton:")
    parts.append(skel)
    text = _fit_budget(parts, max_chars)
    return CompressResult("skeleton", text, len(enriched), len(text))


def compress_card(enriched: str, *, max_chars: int = MAX_CHARS_DEFAULT) -> CompressResult:
    header, body = split_enriched(enriched)
    meta = _parse_meta_lines(header)
    sigs, calls, types = _signatures_and_calls(body)
    doc = _docstring_from_body(body)
    parts: list[str] = [
        f"Repository: {meta.get('repository') or ''}",
        f"File: {meta.get('file') or ''}",
        f"Module: {meta.get('module') or ''}",
        f"Folder: {meta.get('folder') or ''}",
    ]
    fns = meta.get("functions") or []
    if isinstance(fns, list) and fns:
        parts.append("Symbol: " + ", ".join(fns[:6]))
    if sigs:
        parts.append("Signature: " + " | ".join(sigs[:3])[:200])
    imps = meta.get("imports") or []
    if isinstance(imps, list) and imps:
        parts.append("Imports: " + ", ".join(imps[:12]))
    exps = meta.get("exports") or []
    if isinstance(exps, list) and exps:
        parts.append("Exports: " + ", ".join(exps[:8]))
    if calls:
        parts.append("APIs: " + ", ".join(calls[:16]))
    if types:
        parts.append("Types: " + ", ".join(types[:10]))
    related = meta.get("related") or []
    if isinstance(related, list) and related:
        parts.append("Related: " + ", ".join(related[:6]))
    deps = meta.get("dependents") or []
    if isinstance(deps, list) and deps:
        parts.append("Called-by: " + ", ".join(deps[:8]))
    if doc:
        parts.append("Intent: " + doc)
    text = _fit_budget(parts, max_chars, soft=TARGET_SOFT)
    # fill remainder with tiny body excerpt only if budget left
    if len(text) < TARGET_MIN and body.strip():
        remain = max_chars - len(text) - 1
        if remain > 40:
            excerpt = _trim_to_budget(body.strip(), remain)
            text = _trim_to_budget(text + "\n" + excerpt, max_chars)
    return CompressResult("card", text, len(enriched), len(text))


def _idf_weight(token: str, freq: dict[str, int], n_docs: int = 1) -> float:
    # local rarity within chunk: rarer tokens score higher
    f = freq.get(token, 1)
    return math.log(1.0 + (len(freq) + 1) / f)


def compress_importance(enriched: str, *, max_chars: int = MAX_CHARS_DEFAULT) -> CompressResult:
    header, body = split_enriched(enriched)
    meta = _parse_meta_lines(header)
    sigs, calls, types = _signatures_and_calls(body)
    doc = _docstring_from_body(body)

    # Seed high-priority lines first
    priority_lines: list[tuple[float, str]] = []
    file = str(meta.get("file") or "")
    priority_lines.append((100.0, f"File: {file}"))
    priority_lines.append((95.0, f"Module: {meta.get('module') or ''}"))
    for fn in (meta.get("functions") or [])[:8]:
        if isinstance(fn, str):
            priority_lines.append((90.0, f"Function: {fn}"))
    for s in sigs[:4]:
        priority_lines.append((88.0, s[:180]))
    for imp in (meta.get("imports") or [])[:12]:
        if isinstance(imp, str):
            priority_lines.append((80.0, f"import {imp}"))
    for exp in (meta.get("exports") or [])[:8]:
        if isinstance(exp, str):
            priority_lines.append((78.0, f"export {exp}"))
    for c in calls[:16]:
        priority_lines.append((70.0, f"call {c}"))
    for t in types[:10]:
        priority_lines.append((65.0, f"type {t}"))
    for d in (meta.get("dependents") or [])[:8]:
        if isinstance(d, str):
            priority_lines.append((72.0, f"dependent {d}"))
    if doc:
        priority_lines.append((85.0, f"doc: {doc}"))

    # Score remaining body tokens into phrases (lines)
    tokens = [t.lower() for t in _IDENT.findall(body)]
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1

    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("logger.", "print(", "logging.")):
            continue
        idents = _IDENT.findall(s)
        if not idents:
            continue
        score = 0.0
        for tok in idents:
            tl = tok.lower()
            if tl in _STOP_KW or len(tl) <= 1:
                score += 0.05
                continue
            score += 1.5 * _idf_weight(tl, freq)
            if tok[0].isupper() or "_" in tok:
                score += 2.0  # CamelCase / snake identifiers
            if tl in {c.lower() for c in calls}:
                score += 3.0
        # demote pure control-flow short lines
        if re.match(r"^(if|else|elif|for|while|try|except)\b", s):
            score *= 0.15
        if score >= 4.0:
            priority_lines.append((score, s[:160]))

    # Sort by score desc, unique text
    priority_lines.sort(key=lambda x: -x[0])
    seen: set[str] = set()
    packed: list[str] = []
    n = 0
    for _, line in priority_lines:
        key = line.strip()
        if key in seen:
            continue
        seen.add(key)
        add = len(key) + (1 if packed else 0)
        if n + add > max_chars:
            remain = max_chars - n - (1 if packed else 0)
            if remain >= 20:
                packed.append(_trim_to_budget(key, remain))
            break
        packed.append(key)
        n += add
        if n >= TARGET_SOFT and len(packed) >= 6:
            break
    text = _trim_to_budget("\n".join(packed), max_chars)
    return CompressResult("importance", text, len(enriched), len(text))


def _importance_body_lines(body: str, calls: list[str]) -> list[tuple[float, str]]:
    """Score body lines the same way as compress_importance (body only)."""
    tokens = [t.lower() for t in _IDENT.findall(body)]
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t] = freq.get(t, 0) + 1
    call_set = {c.lower() for c in calls}
    scored: list[tuple[float, str]] = []
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("logger.", "print(", "logging.")):
            continue
        idents = _IDENT.findall(s)
        if not idents:
            continue
        score = 0.0
        for tok in idents:
            tl = tok.lower()
            if tl in _STOP_KW or len(tl) <= 1:
                score += 0.05
                continue
            score += 1.5 * _idf_weight(tl, freq)
            if tok[0].isupper() or "_" in tok:
                score += 2.0
            if tl in call_set:
                score += 3.0
        if re.match(r"^(if|else|elif|for|while|try|except)\b", s):
            score *= 0.15
        if score >= 4.0:
            scored.append((score, s[:160]))
    scored.sort(key=lambda x: -x[0])
    return scored


def compress_mix(enriched: str, *, max_chars: int = MAX_CHARS_DEFAULT) -> CompressResult:
    """Hybrid: card's labeled retrieval fields + importance's scored body fill.

    Why each parent wins (52-query soft bakeoff):
      card       — Folder/Intent/Related/Signature labels → better R@1 / MRR
      importance — rare body identifiers / call sites → better R@5 coverage

    Same hard cap as parents (default 512). Card core first (~soft half),
    then pack importance-scored body lines into the remainder.
    """
    header, body = split_enriched(enriched)
    meta = _parse_meta_lines(header)
    sigs, calls, types = _signatures_and_calls(body)
    doc = _docstring_from_body(body)

    # --- Phase A: card-style labeled core (path + intent vocabulary) ---
    core: list[str] = [
        f"File: {meta.get('file') or ''}",
        f"Module: {meta.get('module') or ''}",
        f"Folder: {meta.get('folder') or ''}",
    ]
    fns = meta.get("functions") or []
    if isinstance(fns, list) and fns:
        core.append("Symbol: " + ", ".join(fns[:6]))
    if sigs:
        core.append("Signature: " + " | ".join(sigs[:3])[:180])
    if doc:
        core.append("Intent: " + doc)
    imps = meta.get("imports") or []
    if isinstance(imps, list) and imps:
        core.append("Imports: " + ", ".join(imps[:10]))
    exps = meta.get("exports") or []
    if isinstance(exps, list) and exps:
        core.append("Exports: " + ", ".join(exps[:6]))
    if calls:
        core.append("APIs: " + ", ".join(calls[:12]))
    if types:
        core.append("Types: " + ", ".join(types[:8]))
    related = meta.get("related") or []
    if isinstance(related, list) and related:
        core.append("Related: " + ", ".join(related[:5]))
    deps = meta.get("dependents") or []
    if isinstance(deps, list) and deps:
        core.append("Called-by: " + ", ".join(deps[:6]))

    # Reserve room for body fill (~45% leftover when core is rich).
    core_budget = max(180, min(int(max_chars * 0.55), max_chars - 120))
    core_text = _fit_budget(core, core_budget, soft=min(TARGET_SOFT, core_budget))
    packed = [core_text] if core_text else []
    n = len(core_text)

    # --- Phase B: importance body fill into leftover budget ---
    if n < max_chars - 40 and body.strip():
        seen = {ln.strip() for ln in core_text.splitlines() if ln.strip()}
        for _, line in _importance_body_lines(body, calls):
            key = line.strip()
            if not key or key in seen:
                continue
            # skip exact payload already quoted in a labeled field
            if key in core_text or f" {key}" in core_text:
                continue
            add = len(key) + (1 if packed else 0)
            if n + add > max_chars:
                leftover = max_chars - n - (1 if packed else 0)
                if leftover >= 24:
                    packed.append(_trim_to_budget(key, leftover))
                break
            packed.append(key)
            seen.add(key)
            n += add
            if n >= TARGET_SOFT and len(packed) >= 5:
                break

    text = _trim_to_budget("\n".join(packed), max_chars)
    return CompressResult("mix", text, len(enriched), len(text))


@dataclass(frozen=True)
class BudgetAlloc:
    """Fractional spend of a fixed char budget (must sum ≈ 1.0)."""

    name: str
    metadata: float  # path / folder / graph
    symbols: float  # symbol + signature + intent
    apis: float  # imports / exports / calls / types
    body: float  # rare-identifier fill


BUDGET_PRESETS: dict[str, BudgetAlloc] = {
    "budget_a": BudgetAlloc("budget_a", metadata=0.40, symbols=0.30, apis=0.20, body=0.10),
    "budget_b": BudgetAlloc("budget_b", metadata=0.25, symbols=0.25, apis=0.20, body=0.30),
    "budget_c": BudgetAlloc("budget_c", metadata=0.20, symbols=0.20, apis=0.10, body=0.50),
}


def _slice_budget(total: int, frac: float, *, minimum: int = 0) -> int:
    return max(minimum, int(round(total * frac)))


def _pack_into(parts: list[str], budget: int) -> str:
    if budget <= 0:
        return ""
    return _fit_budget(parts, budget, soft=budget)


def _rare_identifier_fill(
    body: str,
    calls: list[str],
    types: list[str],
    *,
    budget: int,
    already: str,
) -> str:
    """Spend remaining budget on rare / distinctive identifiers (not first-N body)."""
    if budget < 24 or not body.strip():
        return ""
    tokens = [t for t in _IDENT.findall(body) if len(t) > 2]
    freq: dict[str, int] = {}
    for t in tokens:
        freq[t.lower()] = freq.get(t.lower(), 0) + 1
    already_l = already.lower()
    call_set = {c.lower() for c in calls}
    type_set = {t.lower() for t in types}

    scored: list[tuple[float, str]] = []
    seen: set[str] = set()
    for tok in tokens:
        tl = tok.lower()
        if tl in seen or tl in _STOP_KW:
            continue
        seen.add(tl)
        if tl in already_l:
            continue
        score = _idf_weight(tl, freq)
        if tok[0].isupper() or "_" in tok:
            score += 2.0
        if tl in call_set:
            score += 3.0
        if tl in type_set:
            score += 2.5
        if len(tok) >= 8:
            score += 1.0
        # demote very common short locals
        if freq.get(tl, 1) >= 6 and len(tok) < 6:
            score *= 0.2
        scored.append((score, tok))
    scored.sort(key=lambda x: -x[0])

    # also pull high-scoring body lines that introduce rare idents
    line_bits: list[str] = []
    for _, line in _importance_body_lines(body, calls)[:24]:
        if line.lower() in already_l:
            continue
        line_bits.append(line)

    parts: list[str] = []
    if scored:
        names = [t for _, t in scored[:40]]
        parts.append("Rare: " + ", ".join(names))
    parts.extend(line_bits[:12])
    return _pack_into(parts, budget)


def compress_budget(
    enriched: str,
    *,
    max_chars: int = TARGET_SOFT,
    alloc: BudgetAlloc | None = None,
    preset: str = "budget_b",
) -> CompressResult:
    """Fixed-budget allocator: spend chars by field family, fill body with rare idents."""
    alloc = alloc or BUDGET_PRESETS.get(preset) or BUDGET_PRESETS["budget_b"]
    header, body = split_enriched(enriched)
    meta = _parse_meta_lines(header)
    sigs, calls, types = _signatures_and_calls(body)
    doc = _docstring_from_body(body)

    # Hard total — prefer TARGET_SOFT band unless caller asks higher
    total = max(280, min(max_chars, MAX_CHARS_DEFAULT))
    b_meta = _slice_budget(total, alloc.metadata, minimum=40)
    b_sym = _slice_budget(total, alloc.symbols, minimum=40)
    b_api = _slice_budget(total, alloc.apis, minimum=24)
    b_body = max(0, total - b_meta - b_sym - b_api)

    meta_parts = [
        f"File: {meta.get('file') or ''}",
        f"Module: {meta.get('module') or ''}",
        f"Folder: {meta.get('folder') or ''}",
    ]
    related = meta.get("related") or []
    if isinstance(related, list) and related:
        meta_parts.append("Related: " + ", ".join(related[:6]))
    deps = meta.get("dependents") or []
    if isinstance(deps, list) and deps:
        meta_parts.append("Called-by: " + ", ".join(deps[:6]))

    sym_parts: list[str] = []
    fns = meta.get("functions") or []
    if isinstance(fns, list) and fns:
        sym_parts.append("Symbol: " + ", ".join(fns[:8]))
    if sigs:
        sym_parts.append("Signature: " + " | ".join(sigs[:4])[:220])
    if doc:
        sym_parts.append("Intent: " + doc)

    api_parts: list[str] = []
    imps = meta.get("imports") or []
    if isinstance(imps, list) and imps:
        api_parts.append("Imports: " + ", ".join(imps[:14]))
    exps = meta.get("exports") or []
    if isinstance(exps, list) and exps:
        api_parts.append("Exports: " + ", ".join(exps[:8]))
    if calls:
        api_parts.append("APIs: " + ", ".join(calls[:18]))
    if types:
        api_parts.append("Types: " + ", ".join(types[:10]))

    meta_txt = _pack_into(meta_parts, b_meta)
    sym_txt = _pack_into(sym_parts, b_sym)
    api_txt = _pack_into(api_parts, b_api)
    core = "\n".join(p for p in (meta_txt, sym_txt, api_txt) if p)
    used = len(core)
    # unused slice from empty sections rolls into rare-ident body
    remain = max(b_body, total - used - (1 if core else 0))
    body_txt = _rare_identifier_fill(body, calls, types, budget=remain, already=core)

    pieces = [p for p in (core, body_txt) if p]
    text = _trim_to_budget("\n".join(pieces), total)
    return CompressResult(alloc.name, text, len(enriched), len(text))


def compress_budget_a(enriched: str, *, max_chars: int = TARGET_SOFT) -> CompressResult:
    return compress_budget(enriched, max_chars=max_chars, preset="budget_a")


def compress_budget_b(enriched: str, *, max_chars: int = TARGET_SOFT) -> CompressResult:
    return compress_budget(enriched, max_chars=max_chars, preset="budget_b")


def compress_budget_c(enriched: str, *, max_chars: int = TARGET_SOFT) -> CompressResult:
    return compress_budget(enriched, max_chars=max_chars, preset="budget_c")


def prepare_enriched_from_parts(
    file: str,
    symbol: str | None,
    text: str,
    enriched: str,
) -> str:
    """Rebuild enrich text when stored blob was truncated mid-header (no separator)."""
    from pathlib import Path

    src = (enriched or "").strip()
    if _META_SEP in src:
        return src
    body = (text or "").strip() or src
    sym = symbol or "(none)"
    p = Path(file) if file else Path(".")
    header = "\n".join(
        [
            "Repository: (repo)",
            f"Module: {p.parts[0] if p.parts else ''}",
            f"Folder: {p.parent.as_posix() if str(p.parent) != '.' else ''}",
            f"File: {file}",
            "",
            "Functions:",
            f"- {sym}",
            "",
            "Imports:",
            "- (none)",
            "",
            "Exports:",
            f"- {sym}",
            "",
            "Graph Context:",
            "- Related Files: (none)",
            "",
            _META_SEP,
            "",
        ]
    )
    return header + body


COMPRESSORS: dict[str, Callable[..., CompressResult]] = {
    "none": lambda enriched, max_chars=MAX_CHARS_DEFAULT: CompressResult(
        "none", _trim_to_budget(enriched, max_chars), len(enriched), min(len(enriched), max_chars)
    ),
    "baseline": lambda enriched, max_chars=MAX_CHARS_DEFAULT: CompressResult(
        "baseline",
        _trim_to_budget(enriched, max_chars),
        len(enriched),
        min(len(enriched.strip()), max_chars) if enriched.strip() else 0,
    ),
    "skeleton": compress_skeleton,
    "card": compress_card,
    "importance": compress_importance,
    "mix": compress_mix,
    "budget_a": compress_budget_a,
    "budget_b": compress_budget_b,
    "budget_c": compress_budget_c,
}


def compress_chunk(
    enriched: str,
    mode: str,
    *,
    max_chars: int = MAX_CHARS_DEFAULT,
) -> CompressResult:
    key = (mode or "none").strip().lower()
    if key in {"", "none", "off"}:
        key = "baseline"
    fn = COMPRESSORS.get(key)
    if fn is None:
        raise ValueError(f"unknown compress mode: {mode}")
    return fn(enriched, max_chars=max_chars)


def resolve_compress_mode(
    explicit: str | None = None,
    *,
    default: str = "mix",
) -> str | None:
    """Resolve compress mode. Default ships ``mix``; ``off``/``none``/``0`` disables."""
    import os

    if explicit is not None:
        raw = explicit
    else:
        raw = os.environ.get("CTX_COMPRESS", default)
    key = (raw or default).strip().lower()
    if key in {"", "off", "none", "0"}:
        return None
    if key not in COMPRESSORS and key != "baseline":
        raise ValueError(f"unknown compress mode: {raw}")
    return key
