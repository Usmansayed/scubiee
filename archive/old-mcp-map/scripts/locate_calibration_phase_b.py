#!/usr/bin/env python3
"""Phase B offline calibration — M1 / M2 / N1 / E1 / C1 arms.

North star metrics: rounds, result_tokens, total_proxy (= results + rounds*TAX),
must_file / must_sym recall. No GATE/MCP text changes.

Arms
----
M1a  map → (virtual) read top-5 card locs
M1b  map → pack(lean) → (virtual) read heatmap top
M2b  map-first on needle (over-use probe)
N1a  host Grep-style literal search (needle/name controls)
E1a  map→pack→expand(callees) recovery
E1b  map→pack→+3 Greps on heatmap files
E1c  map→pack(strict)→pack(broad) recovery
C1a  map→pack→collect_hot(threshold)
C1b  map→pack→K span-Reads

Usage:
  PYTHONPATH=packages python scripts/locate_calibration_phase_b.py
  PYTHONPATH=packages python scripts/locate_calibration_phase_b.py --limit-soft 8 --limit-ec 6
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs" / "superpowers" / "plans" / "locate-calibration-corpus-v1.json"
OUT_JSON = ROOT / "docs" / "superpowers" / "plans" / "locate-calibration-phase-b-results.json"
OUT_MD = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-locate-calibration-phase-b.md"
RUN_DIR = ROOT / "docs" / "superpowers" / "plans" / "locate-calibration-runs"

# Proxy for repeated system/tool/conversation tax per round-trip (tokens).
# Calibrate later from host traces; keep constant for relative comparisons.
ROUND_TRIP_TAX = int(os.environ.get("CTX_CALIB_ROUND_TAX", "2500"))


def _tokens(s: str | bytes | None) -> int:
    if s is None:
        return 0
    if isinstance(s, bytes):
        s = s.decode("utf-8", errors="replace")
    return max(1, len(s) // 4) if s else 0


def _json_tokens(obj: Any) -> int:
    try:
        return _tokens(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        return _tokens(str(obj))


def _norm_file(p: str) -> str:
    return str(p or "").replace("\\", "/").lstrip("./")


def _score(
    files: set[str],
    symbols: set[str],
    must_files: list[str],
    must_symbols: list[str],
) -> dict[str, Any]:
    files_n = {_norm_file(f) for f in files}
    syms_n = {str(s) for s in symbols if s}

    def file_hit(g: str) -> bool:
        g = _norm_file(g)
        return any(f == g or f.endswith("/" + g) or g.endswith(f) or g in f or f.endswith(g) for f in files_n)

    def sym_hit(g: str) -> bool:
        g = str(g)
        short = g.split("::")[-1] if "::" in g else g
        return any(
            s == g or s == short or s.endswith("." + short) or short in s or g in s for s in syms_n
        )

    fh = [file_hit(g) for g in must_files] if must_files else []
    sh = [sym_hit(g) for g in must_symbols] if must_symbols else []
    return {
        "must_file": round(sum(fh) / len(fh), 3) if fh else None,
        "must_sym": round(sum(sh) / len(sh), 3) if sh else None,
        "file_hits": sum(fh),
        "file_n": len(fh),
        "sym_hits": sum(sh),
        "sym_n": len(sh),
    }


def _cost(rounds: int, result_tokens: int) -> dict[str, Any]:
    tax = rounds * ROUND_TRIP_TAX
    return {
        "rounds": rounds,
        "result_tokens": result_tokens,
        "round_trip_tax": tax,
        "total_proxy": result_tokens + tax,
        "round_trip_tax_per_call": ROUND_TRIP_TAX,
    }


def _collect_from_cards(cards: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    syms: set[str] = set()
    for c in cards:
        if c.get("file"):
            files.add(_norm_file(str(c["file"])))
        if c.get("symbol"):
            syms.add(str(c["symbol"]))
    return files, syms


def _collect_from_pack(pack: dict[str, Any]) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    syms: set[str] = set()
    for key in ("heatmap", "pack", "cold", "chain"):
        for c in pack.get(key) or []:
            if not isinstance(c, dict):
                continue
            if c.get("file"):
                files.add(_norm_file(str(c["file"])))
            if c.get("symbol"):
                syms.add(str(c["symbol"]))
            if c.get("id") and "::" in str(c["id"]):
                syms.add(str(c["id"]).split("::", 1)[1])
    seed = pack.get("seed")
    if isinstance(seed, dict):
        if seed.get("file"):
            files.add(_norm_file(str(seed["file"])))
        if seed.get("symbol"):
            syms.add(str(seed["symbol"]))
    return files, syms


def _read_span_chars(file: str, start: int, end: int, cap: int = 4000) -> int:
    path = ROOT / file
    if not path.is_file():
        return 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:  # noqa: BLE001
        return 0
    s = max(1, start) - 1
    e = min(len(lines), max(start, end))
    chunk = "\n".join(lines[s:e])
    return min(len(chunk), cap)


def _soft_map_lexical(query: str, *, k: int = 10) -> dict[str, Any]:
    """Index-free soft map fallback for offline calibration when publication is broken."""
    from pipeline.context_trace import fill_map_card_symbol, pick_suggested_seed, symbol_from_preview

    tokens = [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query or "")]
    tokens = [t for t in tokens if t not in {"the", "and", "for", "how", "does", "with", "from", "when"}]
    scored: list[tuple[float, Path]] = []
    for path in (ROOT / "packages").rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        low = text.lower()
        score = 0.0
        for t in tokens:
            score += low.count(t) * (2.0 if t in path.name.lower() else 1.0)
        if score > 0:
            scored.append((score, path))
    scored.sort(key=lambda x: -x[0])
    cards: list[dict[str, Any]] = []
    for i, (score, path) in enumerate(scored[:k], 1):
        rel = _norm_file(str(path.relative_to(ROOT)))
        role = "function"
        if "/test" in f"/{rel.lower()}" or rel.startswith("tests/"):
            role = "test"
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            src = ""
        # Prefer a query-token-matching public def; else first public def in file.
        sym, kind, start, end = "", "function", 1, 1
        lines = src.splitlines()
        best: tuple[int, str, str, int, int] | None = None
        for li, line in enumerate(lines, 1):
            s, knd = symbol_from_preview(line)
            if not s or s.startswith("_"):
                continue
            # rough end: next def/class or +40
            end_l = min(len(lines), li + 40)
            for lj in range(li, min(len(lines), li + 200)):
                if lj > li - 1 and re.match(r"^(?:async\s+)?def\s+|^\s*class\s+", lines[lj]):
                    if lj + 1 > li:
                        end_l = lj
                        break
            hit = sum(1 for t in tokens if t in s.lower() or t in line.lower())
            cand = (hit, s, knd or "function", li, end_l)
            if best is None or cand[0] > best[0]:
                best = cand
        if best:
            _, sym, kind, start, end = best
        cards.append(
            fill_map_card_symbol(
                {
                    "rank": i,
                    "file": rel,
                    "symbol": sym,
                    "kind": kind,
                    "role": role,
                    "score": score,
                    "start_line": start,
                    "end_line": end,
                    "loc": f"{rel}:{start}-{end}",
                    "why": f"def {sym}(" if sym else "",
                }
            )
        )
    suggested = pick_suggested_seed(cards)
    return {
        "ok": True,
        "tool": "map",
        "cards": cards,
        "suggested_seed": suggested,
        "source": "lexical_fallback",
        "count": len(cards),
    }


def _run_map(query: str, *, k: int = 10) -> dict[str, Any]:
    try:
        from pipeline.locate_cli import cli_map

        out = cli_map(query, path=ROOT, k=k, local=True)
        if out.get("ok"):
            return out
    except Exception as exc:  # noqa: BLE001
        fallback = _soft_map_lexical(query, k=k)
        fallback["fallback_error"] = str(exc)[:200]
        return fallback
    return _soft_map_lexical(query, k=k)


def arm_map_read(case: dict[str, Any], *, k: int = 10, top_read: int = 5) -> dict[str, Any]:
    t0 = time.perf_counter()
    mapped = _run_map(case["enrich_query"], k=k)
    cards = list(mapped.get("cards") or [])
    files, syms = _collect_from_cards(cards)
    # Virtual native Reads of top card locs (span chars billed as result tokens too)
    read_chars = 0
    for c in cards[:top_read]:
        f = _norm_file(str(c.get("file") or ""))
        if not f:
            continue
        start = int(c.get("start_line") or 1)
        end = int(c.get("end_line") or start + 40)
        if end <= start:
            end = start + 40
        read_chars += _read_span_chars(f, start, end)
    result_tok = _json_tokens(mapped) + (read_chars // 4)
    rounds = 1 + min(top_read, len(cards))  # map + N reads
    score = _score(files, syms, case.get("must_files") or [], case.get("must_symbols") or [])
    return {
        "arm": "M1a_map_read",
        "ok": bool(mapped.get("ok")),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "seed": mapped.get("suggested_seed"),
        "map_source": mapped.get("source") or "cli_map",
        "n_cards": len(cards),
        "read_chars": read_chars,
        **_cost(rounds, result_tok),
        **score,
    }


def arm_map_pack(case: dict[str, Any], *, k: int = 10) -> dict[str, Any]:
    from pipeline.context_trace import run_pack_context

    t0 = time.perf_counter()
    mapped = _run_map(case["enrich_query"], k=k)
    cards = list(mapped.get("cards") or [])
    sug = mapped.get("suggested_seed") or {}
    seed_file = _norm_file(str(sug.get("file") or ""))
    seed_symbol = str(sug.get("symbol") or "")
    seed_ok = bool(
        seed_file.startswith(("packages/", "src/", "app/"))
        and seed_symbol
        and not seed_symbol.startswith("_")
        and "test" not in seed_file.lower()
    )
    if not seed_file and cards:
        seed_file = _norm_file(str(cards[0].get("file") or ""))
    pack: dict[str, Any] = {"ok": False}
    if seed_file:
        kwargs: dict[str, Any] = {
            "seed_file": seed_file,
            "mode": "lean",
            "policy": "strict",
            "k": 16,
            "include_bodies": False,
        }
        if seed_symbol:
            kwargs["seed_symbol"] = seed_symbol
        try:
            pack = run_pack_context(ROOT, case["enrich_query"], **kwargs)
        except Exception as exc:  # noqa: BLE001
            pack = {"ok": False, "error": str(exc)}
    files_m, syms_m = _collect_from_cards(cards)
    files_p, syms_p = _collect_from_pack(pack if isinstance(pack, dict) else {})
    files, syms = files_m | files_p, syms_m | syms_p
    # Virtual reads of top heatmap locs
    heatmap = list((pack or {}).get("heatmap") or [])[:5]
    read_chars = 0
    for c in heatmap:
        f = _norm_file(str(c.get("file") or ""))
        if not f:
            continue
        start = int(c.get("start_line") or 1)
        end = int(c.get("end_line") or start + 40)
        read_chars += _read_span_chars(f, start, end)
    rounds = 2 + len(heatmap)  # map + pack + reads
    result_tok = _json_tokens(mapped) + _json_tokens(pack) + (read_chars // 4)
    score = _score(files, syms, case.get("must_files") or [], case.get("must_symbols") or [])
    return {
        "arm": "M1b_map_pack",
        "ok": bool(mapped.get("ok")) and bool(pack.get("ok")),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "seed_file": seed_file,
        "seed_symbol": seed_symbol,
        "seed_ok": seed_ok,
        "map_source": mapped.get("source") or "cli_map",
        "heatmap_n": len((pack or {}).get("heatmap") or []),
        "read_chars": read_chars,
        **_cost(rounds, result_tok),
        **score,
    }


def arm_host_grep(case: dict[str, Any]) -> dict[str, Any]:
    """Simulate host Grep: search enrich tokens / must_symbols as literals in packages/."""
    t0 = time.perf_counter()
    patterns: list[str] = []
    for s in case.get("must_symbols") or []:
        patterns.append(str(s).split("::")[-1])
    # also short tokens from enrich (identifiers)
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", case.get("enrich_query") or ""):
        if tok.lower() not in {"that", "this", "with", "from", "when", "where", "does", "how"}:
            patterns.append(tok)
    # de-dupe preserve order
    seen: set[str] = set()
    pats: list[str] = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            pats.append(p)
    pats = pats[:8]

    files: set[str] = set()
    syms: set[str] = set()
    hits: list[dict[str, Any]] = []
    # Prefer searching must_files first if known, else packages/
    search_roots = []
    for mf in case.get("must_files") or []:
        p = ROOT / mf
        if p.is_file():
            search_roots.append(p)
    if not search_roots:
        search_roots = list((ROOT / "packages").rglob("*.py"))[:400]

    for pat in pats:
        rx = re.compile(re.escape(pat))
        for path in search_roots:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            if not rx.search(text):
                continue
            rel = _norm_file(str(path.relative_to(ROOT)))
            files.add(rel)
            syms.add(pat)
            # one hit snippet
            for i, line in enumerate(text.splitlines(), 1):
                if pat in line:
                    hits.append({"file": rel, "line": i, "pat": pat, "preview": line.strip()[:120]})
                    break
            if len(hits) >= 20:
                break
        if len(hits) >= 20:
            break

    # Virtual reads: open each hit file span ~40 lines
    read_chars = 0
    for h in hits[:5]:
        read_chars += _read_span_chars(h["file"], max(1, h["line"] - 5), h["line"] + 35)

    # rounds: 1 grep (+ optional glob for name_path) + reads
    rounds = 1 + min(5, len({h["file"] for h in hits}))
    if case.get("taxonomy") == "name_path":
        rounds = 1 + 1  # glob + read
        # glob simulation: file exists
        for mf in case.get("must_files") or []:
            if (ROOT / mf).is_file():
                files.add(_norm_file(mf))

    payload = {"hits": hits[:20], "patterns": pats}
    result_tok = _json_tokens(payload) + (read_chars // 4)
    score = _score(files, syms, case.get("must_files") or [], case.get("must_symbols") or [])
    return {
        "arm": "N1a_host_grep",
        "ok": bool(hits) or bool(files),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "n_hits": len(hits),
        "patterns": pats,
        "read_chars": read_chars,
        **_cost(rounds, result_tok),
        **score,
    }


def arm_map_on_needle(case: dict[str, Any]) -> dict[str, Any]:
    """Over-use probe: run map(+reads) on a needle/name task."""
    out = arm_map_read(case, k=8, top_read=3)
    out["arm"] = "M2b_map_on_needle"
    return out


def _map_pack(
    case: dict[str, Any],
    *,
    k: int = 10,
    policy: str = "strict",
    pack_k: int = 16,
) -> dict[str, Any]:
    """Shared map→pack lean base for E1/C1 arms."""
    from pipeline.context_trace import run_pack_context

    mapped = _run_map(case["enrich_query"], k=k)
    cards = list(mapped.get("cards") or [])
    sug = mapped.get("suggested_seed") or {}
    seed_file = _norm_file(str(sug.get("file") or ""))
    seed_symbol = str(sug.get("symbol") or "")
    if not seed_file and cards:
        seed_file = _norm_file(str(cards[0].get("file") or ""))
        if not seed_symbol:
            seed_symbol = str(cards[0].get("symbol") or "")
    seed_ok = bool(
        seed_file.startswith(("packages/", "src/", "app/"))
        and seed_symbol
        and not seed_symbol.startswith("_")
        and "test" not in seed_file.lower()
    )
    pack: dict[str, Any] = {"ok": False}
    if seed_file:
        kwargs: dict[str, Any] = {
            "seed_file": seed_file,
            "mode": "lean",
            "policy": policy,
            "k": pack_k,
            "include_bodies": False,
        }
        if seed_symbol:
            kwargs["seed_symbol"] = seed_symbol
        try:
            pack = run_pack_context(ROOT, case["enrich_query"], **kwargs)
        except Exception as exc:  # noqa: BLE001
            pack = {"ok": False, "error": str(exc)[:240]}
    seed_id = str(((pack or {}).get("seed") or {}).get("id") or "")
    heatmap = list((pack or {}).get("heatmap") or [])
    if not seed_id and heatmap:
        seed_id = str(heatmap[0].get("id") or "")
    return {
        "mapped": mapped,
        "pack": pack,
        "cards": cards,
        "heatmap": heatmap,
        "seed_file": seed_file,
        "seed_symbol": seed_symbol,
        "seed_ok": seed_ok,
        "seed_id": seed_id,
        "map_source": mapped.get("source") or "cli_map",
    }


def arm_e1_expand(case: dict[str, Any]) -> dict[str, Any]:
    """E1a: map→pack(strict)→expand(callees) + virtual reads of delta."""
    from pipeline.context_trace import run_expand_context

    t0 = time.perf_counter()
    base = _map_pack(case, policy="strict")
    expand: dict[str, Any] = {"ok": False}
    if base["seed_id"]:
        try:
            expand = run_expand_context(
                ROOT,
                base["seed_id"],
                query=case["enrich_query"],
                direction="callees",
                k=12,
                with_bodies=False,
            )
        except Exception as exc:  # noqa: BLE001
            expand = {"ok": False, "error": str(exc)[:240]}
    delta = list((expand or {}).get("delta") or [])
    files_m, syms_m = _collect_from_cards(base["cards"])
    files_p, syms_p = _collect_from_pack(base["pack"] if isinstance(base["pack"], dict) else {})
    files_e, syms_e = _collect_from_cards(delta)
    files, syms = files_m | files_p | files_e, syms_m | syms_p | syms_e
    read_chars = 0
    for c in delta[:3]:
        f = _norm_file(str(c.get("file") or ""))
        if not f:
            continue
        start = int(c.get("start_line") or 1)
        end = int(c.get("end_line") or start + 40)
        read_chars += _read_span_chars(f, start, end)
    rounds = 3 + min(3, len(delta))  # map + pack + expand + reads
    result_tok = (
        _json_tokens(base["mapped"])
        + _json_tokens(base["pack"])
        + _json_tokens(expand)
        + (read_chars // 4)
    )
    score = _score(files, syms, case.get("must_files") or [], case.get("must_symbols") or [])
    return {
        "arm": "E1a_expand",
        "ok": bool(base["mapped"].get("ok")) and bool((base["pack"] or {}).get("ok")) and bool(expand.get("ok")),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "seed_ok": base["seed_ok"],
        "map_source": base["map_source"],
        "delta_n": len(delta),
        "read_chars": read_chars,
        **_cost(rounds, result_tok),
        **score,
    }


def arm_e1_grep_recover(case: dict[str, Any]) -> dict[str, Any]:
    """E1b: map→pack→+3 Greps on heatmap files (native recovery hop)."""
    t0 = time.perf_counter()
    base = _map_pack(case, policy="strict")
    heat_files = [
        _norm_file(str(c.get("file") or ""))
        for c in base["heatmap"][:8]
        if c.get("file")
    ]
    pats: list[str] = []
    for s in case.get("must_symbols") or []:
        pats.append(str(s).split("::")[-1])
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", case.get("enrich_query") or ""):
        if tok.lower() not in {"that", "this", "with", "from", "when", "where", "does", "how"}:
            pats.append(tok)
    seen: set[str] = set()
    uniq = []
    for p in pats:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    uniq = uniq[:3]

    files_m, syms_m = _collect_from_cards(base["cards"])
    files_p, syms_p = _collect_from_pack(base["pack"] if isinstance(base["pack"], dict) else {})
    files, syms = files_m | files_p, syms_m | syms_p
    hits: list[dict[str, Any]] = []
    search_paths = [ROOT / f for f in heat_files if (ROOT / f).is_file()]
    if not search_paths:
        search_paths = list((ROOT / "packages").rglob("*.py"))[:80]
    for pat in uniq:
        rx = re.compile(re.escape(pat))
        for path in search_paths:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            if not rx.search(text):
                continue
            rel = _norm_file(str(path.relative_to(ROOT)))
            files.add(rel)
            syms.add(pat)
            for i, line in enumerate(text.splitlines(), 1):
                if pat in line:
                    hits.append({"file": rel, "line": i, "pat": pat})
                    break
            break
    read_chars = 0
    for h in hits[:3]:
        read_chars += _read_span_chars(h["file"], max(1, h["line"] - 5), h["line"] + 35)
    rounds = 2 + len(uniq) + min(3, len(hits))  # map + pack + greps + reads
    result_tok = (
        _json_tokens(base["mapped"])
        + _json_tokens(base["pack"])
        + _json_tokens({"hits": hits, "patterns": uniq})
        + (read_chars // 4)
    )
    score = _score(files, syms, case.get("must_files") or [], case.get("must_symbols") or [])
    return {
        "arm": "E1b_grep_recover",
        "ok": bool(base["mapped"].get("ok")) and bool((base["pack"] or {}).get("ok")),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "seed_ok": base["seed_ok"],
        "map_source": base["map_source"],
        "n_hits": len(hits),
        "read_chars": read_chars,
        **_cost(rounds, result_tok),
        **score,
    }


def arm_e1_broad_repack(case: dict[str, Any]) -> dict[str, Any]:
    """E1c: map→pack(strict)→pack(broad) recovery (no expand)."""
    from pipeline.context_trace import run_pack_context

    t0 = time.perf_counter()
    base = _map_pack(case, policy="strict")
    broad_pack: dict[str, Any] = {"ok": False}
    if base["seed_file"]:
        kwargs: dict[str, Any] = {
            "seed_file": base["seed_file"],
            "mode": "lean",
            "policy": "broad",
            "k": 16,
            "include_bodies": False,
        }
        if base["seed_symbol"]:
            kwargs["seed_symbol"] = base["seed_symbol"]
        try:
            broad_pack = run_pack_context(ROOT, case["enrich_query"], **kwargs)
        except Exception as exc:  # noqa: BLE001
            broad_pack = {"ok": False, "error": str(exc)[:240]}
    files_m, syms_m = _collect_from_cards(base["cards"])
    files_s, syms_s = _collect_from_pack(base["pack"] if isinstance(base["pack"], dict) else {})
    files_b, syms_b = _collect_from_pack(broad_pack if isinstance(broad_pack, dict) else {})
    files, syms = files_m | files_s | files_b, syms_m | syms_s | syms_b
    heatmap = list((broad_pack or {}).get("heatmap") or [])[:5]
    read_chars = 0
    for c in heatmap:
        f = _norm_file(str(c.get("file") or ""))
        if not f:
            continue
        start = int(c.get("start_line") or 1)
        end = int(c.get("end_line") or start + 40)
        read_chars += _read_span_chars(f, start, end)
    rounds = 3 + len(heatmap)  # map + strict pack + broad pack + reads
    result_tok = (
        _json_tokens(base["mapped"])
        + _json_tokens(base["pack"])
        + _json_tokens(broad_pack)
        + (read_chars // 4)
    )
    score = _score(files, syms, case.get("must_files") or [], case.get("must_symbols") or [])
    return {
        "arm": "E1c_broad_repack",
        "ok": bool(base["mapped"].get("ok"))
        and bool((base["pack"] or {}).get("ok"))
        and bool(broad_pack.get("ok")),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "seed_ok": base["seed_ok"],
        "map_source": base["map_source"],
        "heatmap_n": len((broad_pack or {}).get("heatmap") or []),
        "read_chars": read_chars,
        **_cost(rounds, result_tok),
        **score,
    }


def arm_c1_collect(case: dict[str, Any], *, threshold: float = 0.5, max_bodies: int = 5) -> dict[str, Any]:
    """C1a: map→pack→one collect_hot(threshold) body batch."""
    from pipeline.context_trace import run_collect_hot

    t0 = time.perf_counter()
    base = _map_pack(case, policy="strict")
    collected: dict[str, Any] = {"ok": False, "bodies": []}
    if base["heatmap"]:
        try:
            collected = run_collect_hot(
                ROOT,
                base["heatmap"],
                threshold=threshold,
                max_chars=8000,
                max_bodies=max_bodies,
            )
        except Exception as exc:  # noqa: BLE001
            collected = {"ok": False, "error": str(exc)[:240], "bodies": []}
    bodies = list((collected or {}).get("bodies") or [])
    files_m, syms_m = _collect_from_cards(base["cards"])
    files_p, syms_p = _collect_from_pack(base["pack"] if isinstance(base["pack"], dict) else {})
    files_b = {_norm_file(str(b.get("file") or "")) for b in bodies if b.get("file")}
    syms_b = {str(b.get("symbol") or "") for b in bodies if b.get("symbol")}
    files, syms = files_m | files_p | files_b, syms_m | syms_p | syms_b
    body_chars = sum(len(str(b.get("text") or "")) for b in bodies)
    rounds = 3  # map + pack + collect
    body_meta = []
    for b in bodies:
        meta = {k: v for k, v in b.items() if k != "text"}
        meta["text_chars"] = len(str(b.get("text") or ""))
        body_meta.append(meta)
    collect_bill = {k: v for k, v in collected.items() if k != "bodies"}
    collect_bill["bodies"] = body_meta
    result_tok = (
        _json_tokens(base["mapped"])
        + _json_tokens(base["pack"])
        + _json_tokens(collect_bill)
        + (body_chars // 4)
    )
    score = _score(files, syms, case.get("must_files") or [], case.get("must_symbols") or [])
    return {
        "arm": "C1a_collect",
        "ok": bool(base["mapped"].get("ok"))
        and bool((base["pack"] or {}).get("ok"))
        and bool(collected.get("ok")),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "seed_ok": base["seed_ok"],
        "map_source": base["map_source"],
        "n_bodies": len(bodies),
        "body_chars": body_chars,
        "threshold": threshold,
        **_cost(rounds, result_tok),
        **score,
    }


def arm_c1_span_reads(case: dict[str, Any], *, top_read: int = 5) -> dict[str, Any]:
    """C1b: map→pack→K native span-Reads (no collect)."""
    t0 = time.perf_counter()
    base = _map_pack(case, policy="strict")
    heatmap = base["heatmap"][:top_read]
    files_m, syms_m = _collect_from_cards(base["cards"])
    files_p, syms_p = _collect_from_pack(base["pack"] if isinstance(base["pack"], dict) else {})
    files, syms = files_m | files_p, syms_m | syms_p
    read_chars = 0
    for c in heatmap:
        f = _norm_file(str(c.get("file") or ""))
        if not f:
            continue
        start = int(c.get("start_line") or 1)
        end = int(c.get("end_line") or start + 40)
        read_chars += _read_span_chars(f, start, end)
        if c.get("symbol"):
            syms.add(str(c.get("symbol")))
    rounds = 2 + len(heatmap)
    result_tok = _json_tokens(base["mapped"]) + _json_tokens(base["pack"]) + (read_chars // 4)
    score = _score(files, syms, case.get("must_files") or [], case.get("must_symbols") or [])
    return {
        "arm": "C1b_span_reads",
        "ok": bool(base["mapped"].get("ok")) and bool((base["pack"] or {}).get("ok")),
        "elapsed_s": round(time.perf_counter() - t0, 3),
        "seed_ok": base["seed_ok"],
        "map_source": base["map_source"],
        "n_reads": len(heatmap),
        "read_chars": read_chars,
        **_cost(rounds, result_tok),
        **score,
    }


def mean(vals: list[float | None]) -> float | None:
    xs = [v for v in vals if v is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def summarize(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    subset = [r for r in rows if r.get("arm") == arm]
    if not subset:
        return {"arm": arm, "n": 0}
    return {
        "arm": arm,
        "n": len(subset),
        "mean_total_proxy": mean([r.get("total_proxy") for r in subset]),
        "mean_rounds": mean([r.get("rounds") for r in subset]),
        "mean_result_tokens": mean([r.get("result_tokens") for r in subset]),
        "mean_must_file": mean([r.get("must_file") for r in subset]),
        "mean_must_sym": mean([r.get("must_sym") for r in subset]),
        "mean_elapsed_s": mean([r.get("elapsed_s") for r in subset]),
        "ok_rate": round(sum(1 for r in subset if r.get("ok")) / len(subset), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-soft", type=int, default=10, help="soft_understand cases for M1")
    ap.add_argument("--limit-exact", type=int, default=6, help="exact_edit cases for M1")
    ap.add_argument(
        "--limit-ec",
        type=int,
        default=6,
        help="cases for E1/C1 arms (from soft+exact head)",
    )
    ap.add_argument("--skip-ec", action="store_true", help="skip E1/C1 arms")
    args = ap.parse_args()

    os.environ.setdefault("CTX_TRACE_ENGINE", "composite_v1")
    os.environ.setdefault("CTX_REPO", str(ROOT).replace("\\", "/"))

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    all_cases: list[dict[str, Any]] = list(corpus.get("cases") or [])

    soft = [c for c in all_cases if c.get("taxonomy") == "soft_understand"][: args.limit_soft]
    exact = [c for c in all_cases if c.get("taxonomy") == "exact_edit"][: args.limit_exact]
    needles = [
        c
        for c in all_cases
        if c.get("taxonomy") in {"literal_needle", "name_path"}
        or str(c.get("id") or "").startswith("anchor_")
    ]
    m1_cases = soft + exact
    m2_cases = [c for c in needles if c.get("taxonomy") in {"literal_needle", "name_path"}]
    ec_cases = m1_cases[: args.limit_ec]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    t_all = time.perf_counter()

    print(
        f"M1 cases={len(m1_cases)} M2/N1 cases={len(m2_cases)} "
        f"E1/C1 cases={0 if args.skip_ec else len(ec_cases)} TAX={ROUND_TRIP_TAX}"
    )

    for case in m1_cases:
        cid = case["id"]
        print(f"  M1 {cid} …", flush=True)
        a = arm_map_read(case)
        a["case_id"] = cid
        a["taxonomy"] = case["taxonomy"]
        rows.append(a)
        b = arm_map_pack(case)
        b["case_id"] = cid
        b["taxonomy"] = case["taxonomy"]
        rows.append(b)
        (RUN_DIR / f"{cid}__m1.json").write_text(
            json.dumps({"case": case, "M1a": a, "M1b": b}, indent=2), encoding="utf-8"
        )

    over_use_flags = []
    for case in m2_cases:
        cid = case["id"]
        print(f"  N1/M2 {cid} …", flush=True)
        native = arm_host_grep(case)
        native["case_id"] = cid
        native["taxonomy"] = case["taxonomy"]
        rows.append(native)
        forced = arm_map_on_needle(case)
        forced["case_id"] = cid
        forced["taxonomy"] = case["taxonomy"]
        rows.append(forced)
        over_use = (
            forced.get("total_proxy", 0) > native.get("total_proxy", 0)
            and (native.get("must_file") or 0) >= (forced.get("must_file") or 0) - 0.05
        )
        over_use_flags.append({"case_id": cid, "over_use": over_use, "native": native, "forced_map": forced})
        (RUN_DIR / f"{cid}__n1.json").write_text(
            json.dumps(
                {"case": case, "native": native, "forced_map": forced, "over_use": over_use},
                indent=2,
            ),
            encoding="utf-8",
        )

    if not args.skip_ec:
        for case in ec_cases:
            cid = case["id"]
            print(f"  E1/C1 {cid} …", flush=True)
            bundle: dict[str, Any] = {"case": case}
            for fn in (
                arm_e1_expand,
                arm_e1_grep_recover,
                arm_e1_broad_repack,
                arm_c1_collect,
                arm_c1_span_reads,
            ):
                r = fn(case)
                r["case_id"] = cid
                r["taxonomy"] = case["taxonomy"]
                rows.append(r)
                bundle[r["arm"]] = r
            (RUN_DIR / f"{cid}__ec.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    m1_pairs = []
    for case in m1_cases:
        cid = case["id"]
        a = next(r for r in rows if r["case_id"] == cid and r["arm"] == "M1a_map_read")
        b = next(r for r in rows if r["case_id"] == cid and r["arm"] == "M1b_map_pack")
        pack_better_cost = (b.get("total_proxy") or 0) < (a.get("total_proxy") or 0)
        pack_better_file = (b.get("must_file") or 0) > (a.get("must_file") or 0) + 0.05
        pack_worse_file = (b.get("must_file") or 0) + 0.05 < (a.get("must_file") or 0)
        m1_pairs.append(
            {
                "case_id": cid,
                "taxonomy": case["taxonomy"],
                "seed_ok": b.get("seed_ok"),
                "map_source": b.get("map_source") or a.get("map_source"),
                "map_total": a.get("total_proxy"),
                "pack_total": b.get("total_proxy"),
                "map_file": a.get("must_file"),
                "pack_file": b.get("must_file"),
                "pack_better_cost": pack_better_cost,
                "pack_better_file": pack_better_file,
                "pack_worse_file": pack_worse_file,
                "delta_total": (b.get("total_proxy") or 0) - (a.get("total_proxy") or 0),
            }
        )

    arm_keys = [
        "M1a_map_read",
        "M1b_map_pack",
        "N1a_host_grep",
        "M2b_map_on_needle",
        "E1a_expand",
        "E1b_grep_recover",
        "E1c_broad_repack",
        "C1a_collect",
        "C1b_span_reads",
    ]
    board = {k: summarize(rows, k) for k in arm_keys}

    over_use_rate = (
        round(sum(1 for x in over_use_flags if x["over_use"]) / len(over_use_flags), 3)
        if over_use_flags
        else None
    )

    map_sources = [r.get("map_source") for r in rows if r.get("map_source")]
    lexical_n = sum(1 for s in map_sources if s == "lexical_fallback")
    cli_n = sum(1 for s in map_sources if s == "cli_map")

    report = {
        "protocol": "locate_calibration_phase_b_v2",
        "framework": "docs/superpowers/specs/2026-09-06-locate-force-routing-research-framework.md",
        "round_trip_tax": ROUND_TRIP_TAX,
        "elapsed_s": round(time.perf_counter() - t_all, 2),
        "n_m1_cases": len(m1_cases),
        "n_m2_cases": len(m2_cases),
        "n_ec_cases": 0 if args.skip_ec else len(ec_cases),
        "map_source_counts": {"cli_map": cli_n, "lexical_fallback": lexical_n},
        "scoreboard": board,
        "m1_pairwise": m1_pairs,
        "over_use_rate_on_needles": over_use_rate,
        "over_use_details": [
            {"case_id": x["case_id"], "over_use": x["over_use"]} for x in over_use_flags
        ],
        "findings_draft": [],
        "rows": rows,
    }

    findings = []
    findings.append(
        f"Map source: cli_map={cli_n} lexical_fallback={lexical_n} "
        f"(want lexical=0 for trustworthy M1)."
    )
    if board["M1b_map_pack"].get("mean_total_proxy") and board["M1a_map_read"].get("mean_total_proxy"):
        if board["M1b_map_pack"]["mean_total_proxy"] > board["M1a_map_read"]["mean_total_proxy"]:
            findings.append(
                "M1: map→pack costs more total_proxy than map→read on this sample "
                f"({board['M1b_map_pack']['mean_total_proxy']} vs {board['M1a_map_read']['mean_total_proxy']})."
            )
        mf_a = board["M1a_map_read"].get("mean_must_file")
        mf_b = board["M1b_map_pack"].get("mean_must_file")
        if mf_a is not None and mf_b is not None and mf_b + 0.05 < mf_a:
            findings.append(
                f"M1: pack mean must_file ({mf_b}) below map→read ({mf_a}) — supports conditional pack."
            )
        elif mf_a is not None and mf_b is not None and mf_b > mf_a + 0.05:
            findings.append(
                f"M1: pack improves must_file ({mf_b} vs {mf_a}) — pack earns keep when seed_ok."
            )
    seed_ok_rows = [p for p in m1_pairs if p.get("seed_ok")]
    seed_bad_rows = [p for p in m1_pairs if p.get("seed_ok") is False]
    if seed_ok_rows:
        findings.append(
            f"M1 seed_ok subset n={len(seed_ok_rows)}: "
            f"pack_worse_file={sum(1 for p in seed_ok_rows if p['pack_worse_file'])} "
            f"pack_better_file={sum(1 for p in seed_ok_rows if p['pack_better_file'])}"
        )
    if seed_bad_rows:
        findings.append(
            f"M1 seed_ok=false n={len(seed_bad_rows)}: "
            f"pack_worse_file={sum(1 for p in seed_bad_rows if p['pack_worse_file'])} "
            f"— refuse pack on bad seeds hypothesis."
        )
    if over_use_rate is not None:
        findings.append(
            f"N1/M2 over_use_rate (map costlier than Grep with no file gain): {over_use_rate} "
            f"on {len(over_use_flags)} needle/name cases."
        )
        if board["N1a_host_grep"].get("mean_total_proxy") and board["M2b_map_on_needle"].get(
            "mean_total_proxy"
        ):
            findings.append(
                "Needle cost: Grep "
                f"{board['N1a_host_grep']['mean_total_proxy']} vs map-first "
                f"{board['M2b_map_on_needle']['mean_total_proxy']} total_proxy."
            )
    if board["E1a_expand"].get("n"):
        e_costs = [
            ("E1a_expand", board["E1a_expand"].get("mean_total_proxy")),
            ("E1b_grep_recover", board["E1b_grep_recover"].get("mean_total_proxy")),
            ("E1c_broad_repack", board["E1c_broad_repack"].get("mean_total_proxy")),
        ]
        e_costs = [(n, c) for n, c in e_costs if c is not None]
        if e_costs:
            best = min(e_costs, key=lambda x: x[1])
            findings.append(
                "E1 cheapest recovery arm by mean total_proxy: "
                f"{best[0]}={best[1]} (expand={board['E1a_expand'].get('mean_total_proxy')}, "
                f"grep={board['E1b_grep_recover'].get('mean_total_proxy')}, "
                f"broad={board['E1c_broad_repack'].get('mean_total_proxy')})."
            )
            findings.append(
                "E1 must_file: "
                f"expand={board['E1a_expand'].get('mean_must_file')} "
                f"grep={board['E1b_grep_recover'].get('mean_must_file')} "
                f"broad={board['E1c_broad_repack'].get('mean_must_file')}."
            )
    if board["C1a_collect"].get("n"):
        ca = board["C1a_collect"]
        cb = board["C1b_span_reads"]
        findings.append(
            "C1 density: collect "
            f"proxy={ca.get('mean_total_proxy')} rounds={ca.get('mean_rounds')} "
            f"must_file={ca.get('mean_must_file')} vs span_reads "
            f"proxy={cb.get('mean_total_proxy')} rounds={cb.get('mean_rounds')} "
            f"must_file={cb.get('mean_must_file')}."
        )
    report["findings_draft"] = findings

    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md = [
        "# Locate calibration — Phase B (M1 / M2 / N1 / E1 / C1)",
        "",
        f"**Tax per round:** {ROUND_TRIP_TAX} tokens · **Elapsed:** {report['elapsed_s']}s",
        f"**M1 cases:** {len(m1_cases)} · **Needle/name:** {len(m2_cases)} · "
        f"**E1/C1:** {0 if args.skip_ec else len(ec_cases)}",
        f"**Map source:** cli_map={cli_n} lexical_fallback={lexical_n}",
        "",
        "## Scoreboard",
        "",
        "| Arm | n | total_proxy | rounds | result_tok | must_file | must_sym | ok |",
        "|-----|--:|----------:|------:|-----------:|----------:|---------:|---:|",
    ]
    for key in arm_keys:
        s = board[key]
        if not s.get("n"):
            continue
        md.append(
            f"| `{s.get('arm')}` | {s.get('n')} | {s.get('mean_total_proxy')} | "
            f"{s.get('mean_rounds')} | {s.get('mean_result_tokens')} | "
            f"{s.get('mean_must_file')} | {s.get('mean_must_sym')} | {s.get('ok_rate')} |"
        )
    md += [
        "",
        f"**Over-use rate (needles):** {over_use_rate}",
        "",
        "## Draft findings (not ship decisions)",
        "",
    ]
    for f in findings:
        md.append(f"- {f}")
    md += [
        "",
        "## M1 pairwise (pack − map total_proxy)",
        "",
        "| case | tax | seed_ok | map_src | Δ total | map_file | pack_file |",
        "|------|----:|---------|---------|--------:|---------:|----------:|",
    ]
    for p in m1_pairs:
        md.append(
            f"| `{p['case_id']}` | {p['taxonomy']} | {p['seed_ok']} | {p.get('map_source')} | "
            f"{p['delta_total']} | {p['map_file']} | {p['pack_file']} |"
        )
    md += [
        "",
        "## Next",
        "",
        "- Spot-check taxonomy + seed_ok labels",
        "- Re-run denser samples if map source stays cli_map",
        "- Phase C live A/Bs only after offline bars look stable",
        "- Do **not** ship Prefer/Require text until Phase D",
        "",
        f"Raw: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
        "",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "scoreboard": {k: v for k, v in board.items() if v.get("n")},
                "over_use_rate": over_use_rate,
                "map_source_counts": report["map_source_counts"],
                "findings": findings,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
