"""Pack tracer-engine visibility + broad-escape honesty."""
from __future__ import annotations

from pipeline.context_trace import (
    BROAD_ESCAPE_ENGINE,
    PROD_PACK_ENGINE,
    pack_engine_report,
)


def test_pack_engine_report_default_no_escape() -> None:
    rep = pack_engine_report(
        requested_engine="composite_v1",
        policy="strict",
        ran_engine="composite_v1",
    )
    assert rep["engine"] == "composite_v1"
    assert rep["escape"]["used"] is False


def test_pack_engine_report_broad_escapes_default_engine() -> None:
    """pack_context passes engine=composite_v1; policy=broad must still escape."""
    rep = pack_engine_report(
        requested_engine="composite_v1",
        policy="broad",
        ran_engine=BROAD_ESCAPE_ENGINE,
    )
    assert rep["engine"] == BROAD_ESCAPE_ENGINE
    assert rep["escape"]["used"] is True
    assert rep["escape"]["to"] == BROAD_ESCAPE_ENGINE
    assert rep["escape"]["restored"] == PROD_PACK_ENGINE


def test_pack_engine_report_explicit_alt_engine_ignores_broad() -> None:
    rep = pack_engine_report(
        requested_engine="poly_embed",
        policy="broad",
        ran_engine="poly_embed",
    )
    assert rep["engine"] == "poly_embed"
    assert rep["escape"]["used"] is False
