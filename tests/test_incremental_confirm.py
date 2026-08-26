"""Confirm is only for mistake-scale scopes (home/drive or huge trees)."""

from __future__ import annotations

from pipeline.incremental import DEFAULT_MAX_TOUCH, _confirm_hint, require_index_confirm


def test_default_max_touch_allows_normal_codebases() -> None:
    assert DEFAULT_MAX_TOUCH >= 10_000


def test_confirm_hint_mentions_count_and_confirm() -> None:
    msg = _confirm_hint(30_000, max_touch=DEFAULT_MAX_TOUCH)
    assert "30000 files" in msg or "30,000 files" in msg
    assert "--confirm" in msg
    assert "scubiee sync" in msg or "scubiee init" in msg
    assert "--force" not in msg
