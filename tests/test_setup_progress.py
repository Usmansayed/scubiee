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
    bar.update(250_000_000, 500_000_000, label="Downloading model", unit="bytes")
    bar.set(70, "Embedding model ready")
    bar.set(86, "Calibrating speed")
    bar.set(92, "Saving machine profile")
    bar.set(94, "Registering logon supervisor")
    bar.finish("Ready")
    text = buf.getvalue()
    assert text.count("Runtime installed") == 1
    assert "Hardware detected" in text
    assert "Model ready" in text
    assert "[" in text
    assert "50%" in text
    assert "MB" in text


def test_setup_model_milestones_show_no_fake_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixed model-prep milestones (56-85) are labels, not a measured bar."""
    from pipeline.cli_ui import SetupProgress

    class _TTY(io.StringIO):
        def isatty(self) -> bool:
            return True

    buf = _TTY()
    bar = SetupProgress(stream=buf)
    bar.set(58, "Downloading model…")
    bar.set(64, "Converting to FP16…")
    bar.set(70, "Step 3/3: FP16 model ready")
    bar.finish("Ready")
    text = buf.getvalue()
    assert "Converting to FP16" in text
    assert "%" not in text
