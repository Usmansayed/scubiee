"""MCP session I/O must not recreate repo ``.scubiee`` before ``init``."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.session_isolation import session_data_dir
from pipeline.session_store import load_store


def test_mcp_session_does_not_create_repo_scubiee_when_unenrolled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "proj"
    repo.mkdir()

    session_data_dir(repo, "cursor@test")
    load_store(repo)

    assert not (repo / ".scubiee").exists()
    assert (home / "scratch").is_dir()
