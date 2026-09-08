import io

import pytest


def test_setup_progress_single_bar_and_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.cli_ui import SetupProgress

    class _TTY(io.StringIO):
        def isatty(self) -> bool:
            return True

    buf = _TTY()
    monkeypatch.setattr("pipeline.cli_ui._is_tty", lambda _s=None: True)
    bar = SetupProgress(stream=buf)
    bar.set(10, "Detecting hardware")
    bar.set(16, "Using dml profile")
    bar.set(32, "Embedding runtime already installed")
    bar.set(55, "Runtime already installed")
    bar.set(58, "Downloading model…")
    bar.set(70, "Embedding model ready")
    bar.set(86, "Calibrating speed")
    bar.set(92, "Saving machine profile")
    bar.set(94, "Registering logon supervisor")
    text = buf.getvalue()
    assert text.count("Runtime installed") == 1
    assert "Hardware detected" in text
    assert "Model ready" in text
    assert "[" in text
    assert "%" in text
