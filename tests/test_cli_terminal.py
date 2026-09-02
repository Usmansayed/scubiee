"""Terminal color init and wipe progress UI."""

from __future__ import annotations

import io
import sys

import pytest


@pytest.fixture(autouse=True)
def _reset_terminal_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import pipeline.cli_ui as ui

    monkeypatch.setattr(ui, "_terminal_initialized", False)
    monkeypatch.setattr(ui, "_color_enabled", None)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("SCUBIEE_FORCE_COLOR", raising=False)


def test_supports_color_false_when_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    import pipeline.cli_ui as ui

    monkeypatch.setenv("NO_COLOR", "1")
    ui.init_terminal()
    assert ui._supports_color() is False


def test_supports_color_force_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import pipeline.cli_ui as ui

    monkeypatch.setenv("SCUBIEE_FORCE_COLOR", "1")
    ui.init_terminal()
    assert ui._color_enabled is True


def test_windows_ansi_init_uses_colorama(monkeypatch: pytest.MonkeyPatch) -> None:
    import pipeline.cli_ui as ui

    called: list[str] = []

    class _FakeColorama:
        @staticmethod
        def just_fix_windows_console() -> None:
            called.append("fix")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "colorama", _FakeColorama())
    assert ui._init_windows_ansi() is True
    assert called == ["fix"]


def test_colors_disabled_when_windows_init_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import pipeline.cli_ui as ui

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ui, "_init_windows_ansi", lambda: False)
    ui.init_terminal()
    assert ui._color_enabled is False
    assert ui.colors().enabled is False


def test_wipe_progress_non_tty_emits_lines() -> None:
    from pipeline.cli_ui import WipeProgress

    buf = io.StringIO()
    progress = WipeProgress(stream=buf)
    progress.configure(scope="all", models=True, package=True)
    progress.start()
    progress.step_active("Removing repository data")
    progress.step_finish("Repository data wiped")
    text = buf.getvalue()
    assert "Removing repository data" in text
    assert "Repository data wiped" in text
    assert "[" in text
    assert "%" in text


def test_wipe_progress_tty_uses_carriage_return(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.cli_ui import WipeProgress

    class _TTY(io.StringIO):
        def isatty(self) -> bool:
            return True

    buf = _TTY()
    monkeypatch.setattr("pipeline.cli_ui._is_tty", lambda _s=None: True)
    progress = WipeProgress(stream=buf)
    progress.configure(scope="repo", halt_first=True, restart_engine=False)
    progress.step_active("Preparing")
    progress.step_finish("Prepared")
    text = buf.getvalue()
    assert "\033[1A" in text or "\r" in text
    assert "█" in text or "░" in text
    assert "Prepared" in text


def test_scubiee_banner_plain_when_colors_off() -> None:
    from pipeline.cli_banner import render_scubiee_banner

    text = render_scubiee_banner(enabled=False)
    assert "████" in text
    assert "SCUBI" in text or "██╗" in text
    assert "\033[" not in text


def test_scubiee_banner_gradient_when_colors_on() -> None:
    from pipeline.cli_banner import render_scubiee_banner

    text = render_scubiee_banner(enabled=True)
    assert "\033[1;97m" in text
    assert "████" in text
    assert text.startswith("  ")  # indented inside frame


def test_brand_banner_has_frame_and_spacing() -> None:
    import io

    from pipeline.cli_banner import print_brand_banner

    class _TTY(io.StringIO):
        def isatty(self) -> bool:
            return True

    buf = _TTY()
    print_brand_banner("setup", stream=buf)
    text = buf.getvalue()
    assert text.count("─") >= 52  # top + bottom rules
    assert "> scubiee setup" in text or "scubiee setup" in text
    assert text.startswith("\n")
    assert "\n\n" in text  # breathing room around art

