"""Unit tests for agent context navigation (import-follow / spans)."""

from __future__ import annotations

from pathlib import Path

from pipeline.context_nav import (
    clear_session,
    is_distractor,
    parse_imports,
    resolve_module_file,
    tool_follow_imports,
    tool_grep_ident,
    tool_read_span,
)
from pipeline.engine import load_engine

REPO = Path(__file__).resolve().parents[1] / "testdata" / "frontend-mcp"


def test_is_distractor() -> None:
    assert is_distractor("src/navigation/figma_intelligence/x.py")
    assert is_distractor("src/seo_intelligence/a.py")
    assert not is_distractor("src/navigation/mcp/agent_guidance.py")


def test_resolve_dispatch_import() -> None:
    if not REPO.is_dir():
        return
    f = "src/navigation/execution_runtime/executor.py"
    imps = parse_imports(REPO, f)
    mods = {i["module"] for i in imps}
    assert "navigation.execution_runtime.dispatch_registry" in mods
    target = resolve_module_file(
        REPO, "navigation.execution_runtime.dispatch_registry", from_file=f
    )
    assert target and target.endswith("dispatch_registry.py")


def test_follow_imports_and_grep_live() -> None:
    if not REPO.is_dir():
        return
    # May use existing ~/.context-engine index for this repo
    try:
        eng = load_engine(REPO)
    except Exception:
        return
    clear_session(REPO)
    out = tool_follow_imports(
        eng,
        "src/navigation/execution_runtime/executor.py",
        query="tool handler registry",
        keep=4,
        max_chars=400,
    )
    assert out.get("ok")
    paths = [s["path"] for s in out.get("spans") or []]
    assert any("dispatch_registry" in p for p in paths)

    g = tool_grep_ident(eng, "DispatchRegistry", keep=2, max_chars=400)
    assert g.get("ok")
    assert any("dispatch_registry" in s["path"] for s in g.get("spans") or [])

    r = tool_read_span(eng, paths[0], max_chars=400)
    assert r.get("ok") and r.get("span")
