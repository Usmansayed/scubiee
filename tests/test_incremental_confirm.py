"""Safety gate: auto-touch ≤400 files; larger syncs need --confirm."""

from __future__ import annotations

from pipeline.incremental import DEFAULT_MAX_TOUCH, _confirm_hint


def test_default_max_touch_is_400() -> None:
    assert DEFAULT_MAX_TOUCH == 400


def test_confirm_hint_mentions_count_and_confirm_not_fast() -> None:
    msg = _confirm_hint(429, max_touch=400)
    assert "429 files" in msg
    assert "cap 400" in msg
    assert "--confirm" in msg
    assert "scubiee sync" in msg or "scubiee init" in msg
    assert "--force" not in msg
