"""_pattern_prefilter must stay usable for the lookaround/char-class patterns that
bare-name focus resolution greps with, and must never over-filter."""
from __future__ import annotations

import re

import pytest

from pipeline.map_v3_helpers import _pattern_prefilter

IDENT = "enforce_mcp_warm_contract"
ESC = re.escape(IDENT)
LB, RB = r"(?<![\w$])", r"(?![\w$])"


@pytest.mark.parametrize(
    "pattern",
    [
        LB + ESC + RB,
        LB + ESC + r"\s*[(<]",
        r"(?<=def )" + ESC,
        ESC + r"(?=\()",
    ],
)
def test_lookaround_and_class_patterns_get_a_prefilter(pattern: str) -> None:
    pf = _pattern_prefilter(pattern)
    assert pf is not None
    keep, ci = pf
    assert ci is False
    assert keep(f"x = {IDENT}(1)")
    assert not keep("nothing relevant here")


KW_DEF = (
    r"^\s*(?:(?:pub|public|private|static|async|export)\s+)*"
    r"(?:def|class|function|func|fn|struct|type|val|var|fun)\s+" + ESC + RB
)


def test_keyword_def_pattern_requires_the_name() -> None:
    keep, _ = _pattern_prefilter(KW_DEF)
    assert keep(f"def {IDENT}(x):")
    assert not keep("public static var type fun function x = 1")


def test_top_level_alternation_stays_or() -> None:
    keep, _ = _pattern_prefilter(r"alpha_name|beta_name")
    assert keep("only beta_name here")
    assert keep("only alpha_name here")


@pytest.mark.parametrize(
    "pattern,text",
    [
        (KW_DEF, f"  pub fn {IDENT}"),
        (r"\bload_(?:alpha|beta)_index\b", "load_beta_index"),
        (r"(?:foo_bar)?baz_qux", "baz_qux"),
        (r"(?!foo)bar_baz", "bar_baz"),
        (r"(?<!skip_me)target_name", "target_name"),
        (r"[a-z]+_suffix", "abc_suffix"),
        (r"pre[_-]fix_word", "pre-fix_word"),
    ],
)
def test_prefilter_never_rejects_a_real_match(pattern: str, text: str) -> None:
    assert re.search(pattern, text)
    pf = _pattern_prefilter(pattern)
    if pf is not None:
        keep, ci = pf
        assert keep(text.lower() if ci else text)
