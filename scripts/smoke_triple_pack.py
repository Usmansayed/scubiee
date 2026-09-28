"""E2E smoke: three shipped pack engines with a real symbol seed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(ROOT / "packages"))
    from pipeline.context_trace import _CACHE, run_pack_context

    _CACHE.clear()
    q = (
        "session isolation require_session_id fail closed locate pack "
        "persistence session_store put_span"
    )
    seed_file = "packages/pipeline/session_store.py"
    seed_symbol = "put_span"
    engines = [
        ("pack_context", "composite_v1"),
        ("pack_poly_embed", "poly_embed"),
        ("pack_semantic", "semantic_tracer_fuse"),
    ]
    report = []
    for tool, eng in engines:
        print(f"== {tool} engine={eng} ==")
        out = run_pack_context(
            ROOT,
            q,
            seed_file=seed_file,
            seed_symbol=seed_symbol,
            mode="lean",
            policy="strict",
            engine=eng,
            tool_name=tool,
        )
        n = len(out.get("pack") or [])
        ok = bool(out.get("ok")) and n >= 1 and not out.get("error")
        row = {
            "tool": tool,
            "engine": out.get("engine"),
            "ok": ok,
            "n_pack": n,
            "seed": out.get("seed"),
            "top": [
                {"file": p.get("file"), "symbol": p.get("symbol")}
                for p in (out.get("pack") or [])[:5]
            ],
            "error": out.get("error"),
        }
        report.append(row)
        print(json.dumps(row, indent=2))
        if not ok:
            print("FAIL", tool, file=sys.stderr)
            return 2

    # MCP tool registration presence
    from pipeline.mcp_locate import _phase_tool_names

    names = _phase_tool_names()
    for t in ("pack_context", "pack_poly_embed", "pack_semantic"):
        assert t in names, names
    print("MCP phase tools OK:", [t for t in names if t.startswith("pack")])
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
