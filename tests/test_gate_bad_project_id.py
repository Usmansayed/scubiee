"""BUG-B: a wrong/unresolvable project_id must not read as a bare unmanaged "0".

A non-empty project_id (or explicit root) we cannot resolve is a caller mistake.
It binds a sentinel and gate/status now say `0:badpid` + a hint instead of a bare
`0` that is indistinguishable from a genuinely unmanaged repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import mcp_locate as ml


def test_wrong_project_id_binds_the_unresolved_sentinel(monkeypatch) -> None:
    # No registry match for this id.
    monkeypatch.setattr(ml, "_registry_path_for_project_id", lambda pid: None)
    resolved = ml._resolve_request_repo(project_id="ce_deadbeef")
    assert resolved is not None
    assert resolved.name == ml._UNRESOLVED_PROJECT


def test_empty_project_id_does_not_bind_the_sentinel() -> None:
    # Empty id must fall through (None), not the sentinel — it uses the workspace.
    assert ml._resolve_request_repo(project_id="") is None


def test_request_repo_unresolved_detects_the_sentinel() -> None:
    tok = ml._REQUEST_REPO.set(Path(ml._UNRESOLVED_PROJECT))
    try:
        assert ml._request_repo_unresolved() is True
    finally:
        ml._REQUEST_REPO.reset(tok)
    assert ml._request_repo_unresolved() is False  # default None


def test_good_and_none_bindings_are_not_flagged() -> None:
    tok = ml._REQUEST_REPO.set(Path("C:/some/real/repo"))
    try:
        assert ml._request_repo_unresolved() is False
    finally:
        ml._REQUEST_REPO.reset(tok)


def test_managed_signal_fields_flags_bad_project_id(monkeypatch) -> None:
    monkeypatch.setattr(ml, "_is_repo_managed", lambda: False)
    monkeypatch.setattr(ml, "_ctx_repo_raw", lambda: None)
    monkeypatch.setattr(ml, "_ctx_repo_stale", lambda pin: False)
    monkeypatch.setattr(ml, "_managed_candidates", lambda: [])
    tok = ml._REQUEST_REPO.set(Path(ml._UNRESOLVED_PROJECT))
    try:
        fields = ml._managed_signal_fields(just_checked=True)
    finally:
        ml._REQUEST_REPO.reset(tok)
    assert fields["managed"] is False
    assert fields.get("bad_project_id") is True
    assert "did not resolve" in (fields.get("hint") or "")
