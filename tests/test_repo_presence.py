import json

from pipeline.repo_presence import assess_presence


def _write_project_id(root, project_id):
    marker = root / ".scubiee" / "id.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"project_id": project_id}), encoding="utf-8")


def test_missing_path_is_not_forgettable_immediately(tmp_path):
    path = tmp_path / "gone"

    report = assess_presence(
        "ce_x",
        [str(path)],
        missing_since=None,
        retention_s=86400,
    )

    assert report.state == "missing"
    assert report.project_id == "ce_x"
    assert report.last_path == str(path)
    assert report.live_path is None
    assert report.forget_allowed is False
    assert report.reasons


def test_missing_past_retention_is_forgettable(tmp_path):
    report = assess_presence(
        "ce_x",
        [str(tmp_path / "gone")],
        missing_since=0.0,
        retention_s=1,
        now=10.0,
    )

    assert report.state == "missing"
    assert report.forget_allowed is True


def test_zero_retention_does_not_immediately_allow_forget(tmp_path):
    report = assess_presence(
        "ce_x",
        [str(tmp_path / "gone")],
        missing_since=0.0,
        retention_s=0,
        now=0.0,
    )

    assert report.state == "missing"
    assert report.forget_allowed is False


def test_negative_retention_does_not_immediately_allow_forget(tmp_path):
    report = assess_presence(
        "ce_x",
        [str(tmp_path / "gone")],
        missing_since=0.0,
        retention_s=-10,
        now=0.0,
    )

    assert report.state == "missing"
    assert report.forget_allowed is False


def test_matching_id_is_active(tmp_path):
    root = tmp_path / "repo"
    _write_project_id(root, "ce_x")

    report = assess_presence("ce_x", [str(root)])

    assert report.state == "active"
    assert report.live_path == str(root)
    assert report.forget_allowed is False


def test_live_matching_alias_prevents_forget_after_retention(tmp_path):
    live = tmp_path / "moved-repo"
    _write_project_id(live, "ce_x")

    report = assess_presence(
        "ce_x",
        [str(tmp_path / "old-path"), str(live)],
        missing_since=0.0,
        retention_s=1,
        now=10.0,
    )

    assert report.state == "active"
    assert report.last_path == str(tmp_path / "old-path")
    assert report.live_path == str(live)
    assert report.forget_allowed is False


def test_path_with_different_id_is_replaced(tmp_path):
    root = tmp_path / "repo"
    _write_project_id(root, "other")

    report = assess_presence("ce_x", [str(root)])

    assert report.state == "replaced"
    assert report.live_path is None
    assert report.forget_allowed is False


def test_existing_path_without_id_is_conflict(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()

    report = assess_presence(
        "ce_x",
        [str(root)],
        missing_since=0.0,
        retention_s=1,
        now=10.0,
    )

    assert report.state == "conflict"
    assert report.forget_allowed is False
