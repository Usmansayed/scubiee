"""Install/setup shows one in-place 0–100% bar instead of a log dump."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.progress_ui import InstallProgress, render_bar


def test_render_bar_is_a_single_block_with_percent() -> None:
    zero = render_bar(0, width=10)
    half = render_bar(42, width=10)
    done = render_bar(100, width=10)

    assert zero.startswith("[")
    assert zero.endswith("  0%")
    assert "42%" in half
    assert "100%" in done
    assert half.count("█") + half.count("░") == 10 or half.count("#") + half.count("-") == 10


def test_tty_progress_rewrites_one_line_instead_of_stacking(capsys: pytest.CaptureFixture[str]) -> None:
    bar = InstallProgress(stream=sys_stderr(), tty=True, enabled=True)
    bar.start("This may take a few minutes. Downloading and installing the Scubiee engine.")
    bar.set(20, "Installing GPU runtime")
    bar.set(80, "Downloading embedding model")
    bar.finish("Ready")

    err = bar.stream.getvalue()
    assert "This may take a few minutes" in err
    assert "Downloading and installing the Scubiee engine" in err
    assert err.count("\r") >= 2
    assert "[setup] 1/4" not in err
    assert err.strip().endswith("Ready") or "100%" in err


def sys_stderr() -> io.StringIO:
    buf = io.StringIO()
    buf.isatty = lambda: False  # type: ignore[method-assign]
    return buf


def test_non_tty_does_not_spam_every_pulse() -> None:
    buf = io.StringIO()
    bar = InstallProgress(stream=buf, tty=False, enabled=True)
    bar.start("This may take a few minutes.")
    for pct in range(11, 40):
        bar.pulse("Installing packages", until=40)
    text = buf.getvalue()
    lines = [line for line in text.splitlines() if "%" in line]
    assert len(lines) <= 8


def test_progress_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_PROGRESS", "0")
    buf = io.StringIO()
    bar = InstallProgress(stream=buf)
    bar.start("This may take a few minutes.")
    bar.set(50, "Installing")
    bar.finish("Ready")
    assert buf.getvalue() == ""


def test_pip_install_hides_pip_logs_and_uses_quiet_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline import accel

    seen: dict[str, object] = {}

    class FakeProc:
        returncode = 0

        def __init__(self) -> None:
            self._sent = False
            self.stdout = io.StringIO("Would have dumped a wall of pip text\n")

        def poll(self) -> int | None:
            return 0

        def wait(self) -> int:
            return 0

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            del timeout
            return ("Would have dumped a wall of pip text\n", "")

    def fake_popen(cmd, **kwargs):  # noqa: ANN001
        seen["cmd"] = cmd
        seen["stdout"] = kwargs.get("stdout")
        seen["stderr"] = kwargs.get("stderr")
        seen["env"] = kwargs.get("env") or {}
        return FakeProc()

    monkeypatch.setattr(accel.subprocess, "Popen", fake_popen)
    buf = io.StringIO()
    progress = InstallProgress(stream=buf, tty=False, enabled=True)
    accel.pip_install(["fastembed>=0.4"], progress=progress, start_pct=20, end_pct=50)

    cmd = seen["cmd"]
    # uv path uses --quiet; plain pip uses --progress-bar off. Both set PIP_PROGRESS_BAR.
    if cmd and Path(cmd[0]).name.lower().startswith("uv"):
        assert "--quiet" in cmd
    else:
        assert "--progress-bar" in cmd and "off" in cmd
    env = seen["env"]
    assert env.get("PIP_PROGRESS_BAR") == "off"
    assert seen["stdout"] is accel.subprocess.PIPE
    assert "Would have dumped a wall of pip text" not in buf.getvalue()
    assert "50%" in buf.getvalue() or "Installing" in buf.getvalue() or progress._pct >= 50


def test_cmd_setup_uses_progress_bar_not_step_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pipeline import __main__ as cli
    from pipeline import accel

    monkeypatch.setattr(accel, "load_accel", lambda: None)
    monkeypatch.setattr(
        accel,
        "configure",
        lambda **kwargs: SimpleNamespace(
            profile="dml",
            provider="DmlExecutionProvider",
            batch_size=16,
            envelope={},
            __dict__={"profile": "dml", "batch_size": 16, "envelope": {}},
        ),
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.install_session_runtime",
        lambda: {"ok": True, "desktop": "windows"},
    )
    monkeypatch.setattr(
        "pipeline.mcp_install.write_cursor_mcp",
        lambda *args, **kwargs: {"project": "x", "user": "y"},
    )
    monkeypatch.setitem(__import__("sys").modules, "graphify.extract", SimpleNamespace(extract=lambda: None))
    monkeypatch.setitem(__import__("sys").modules, "graphify.build", SimpleNamespace(build=lambda: None))

    args = argparse.Namespace(
        status=False,
        skip_accel=False,
        skip_install=True,
        skip_model=True,
        skip_bench=True,
        repair=False,
        profile=None,
        repo=".",
        index_path=None,
        register=False,
        host="127.0.0.1",
        port=8765,
        wait=1.0,
    )
    assert cli.cmd_setup(args) == 0
    err = capsys.readouterr().err
    assert "This may take a few minutes" in err
    assert "[setup] 1/4 graphify" not in err
    assert "100%" in err or "Ready" in err or "scubiee init" in err


def test_ast_progress_is_silent_when_quiet(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from graphify.extract import _print_ast_progress

    monkeypatch.setenv("GRAPHIFY_QUIET", "1")
    _print_ast_progress("  AST extraction: 100/319 uncached files (31%) [16 workers]")
    captured = capsys.readouterr()
    assert "AST extraction" not in captured.out
    assert "AST extraction" not in captured.err


def test_cmd_init_shows_index_bar_not_resource_log(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from pipeline import __main__ as cli

    repo = tmp_path / "app"
    repo.mkdir()
    monkeypatch.setattr("pipeline.accel.load_accel", lambda: object())
    monkeypatch.setattr(
        "pipeline.repo_lifecycle.initialize_repo",
        lambda *args, **kwargs: {"ok": True, "project_id": "ce_test", "indexed": True},
    )
    monkeypatch.setattr(
        "pipeline.daemon.ensure_daemon",
        lambda *args, **kwargs: {"ok": True},
    )
    rc = cli.cmd_init(
        argparse.Namespace(path=str(repo), no_index=False, allow_once=False)
    )
    out = capsys.readouterr()
    assert rc == 0
    payload = json.loads(out.out)
    assert payload["ok"] is True
    # Progress bar path (TTY or non-TTY) — must not dump resource/AST noise.
    assert "Ready" in out.err or "Initializing" in out.err or "100%" in out.err
    assert "[resources] index start" not in out.err
    assert "AST extraction" not in out.err
    assert "AST extraction" not in out.out


def test_cmd_setup_succeeds_when_logon_task_access_denied(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pipeline import __main__ as cli
    from pipeline import accel

    monkeypatch.setattr(accel, "load_accel", lambda: None)
    monkeypatch.setattr(
        accel,
        "configure",
        lambda **kwargs: SimpleNamespace(profile="dml", __dict__={"profile": "dml"}),
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.install_session_runtime",
        lambda: {
            "ok": True,
            "autostart": {
                "ok": False,
                "detail": "ERROR: Access is denied.\n",
            },
            "supervisor": {"ok": True, "started": True, "pid": 19428},
            "warning": "logon autostart not registered; supervisor is running for this session",
        },
    )
    monkeypatch.setattr(
        "pipeline.mcp_install.write_cursor_mcp",
        lambda *args, **kwargs: {"project": "x", "user": "y"},
    )

    args = argparse.Namespace(
        status=False,
        skip_accel=False,
        skip_install=True,
        skip_model=True,
        skip_bench=True,
        repair=False,
        profile=None,
        repo=".",
        index_path=None,
        register=False,
        host="127.0.0.1",
        port=8765,
        wait=1.0,
    )
    assert cli.cmd_setup(args) == 0
    err = capsys.readouterr().err
    assert "Failed:" not in err
    assert "Access is denied" not in err
    assert "Ready" in err or "100%" in err or "scubiee init" in err
