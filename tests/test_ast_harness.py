import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from parse_harness.bakeoff import assert_deterministic, run_bakeoff
from parse_harness.graphify_adapter import parse_with_graphify

FIXTURE = ROOT / "fixtures" / "mini-repo"
SCUBIEE = ROOT / "testdata" / "scubiee-news-flow"


def test_fixture_determinism():
    a, b = assert_deterministic(FIXTURE)
    assert a.stats["file_count"] >= 3
    assert a.canonical_json(structural_only=True) == b.canonical_json(structural_only=True)


def test_fixture_gold_symbols_and_imports():
    ir = parse_with_graphify(FIXTURE, parallel=False)

    # Function names present
    names = {s.name for s in ir.symbols.values()}
    for expected in {
        "login",
        "loginAsync",
        "validatePassword",
        "validateUsername",
        "createJWT",
        "decodeJWT",
    }:
        assert expected in names, f"missing symbol {expected}; have {sorted(names)}"

    # login.ts imports validatePassword + createJWT
    login_files = [p for p in ir.files if p.endswith("auth/login.ts")]
    assert login_files, f"login.ts missing from {list(ir.files)}"
    login = ir.files[login_files[0]]
    assert "validatePassword" in login.imports
    assert "createJWT" in login.imports

    # contains edges for login.ts callables
    assert "login" in login.exports or "login" in login.symbols
    assert "loginAsync" in login.exports or "loginAsync" in login.symbols

    # call edge loginAsync -> login
    call_pairs = {
        (ir.symbols[e.source].name, ir.symbols[e.target].name)
        for e in ir.edges
        if e.relation == "calls" and e.source in ir.symbols and e.target in ir.symbols
    }
    assert ("loginAsync", "login") in call_pairs


def test_fixture_bakeoff_picks_graphify(tmp_path):
    report = run_bakeoff(FIXTURE, out_dir=tmp_path)
    assert report["winner_parser"] == "graphify"
    assert report["claude_context"]["structural_ir_support"] is False
    assert (tmp_path / "repo_ir.json").exists()
    assert (tmp_path / "bakeoff.json").exists()


@pytest.mark.slow
@pytest.mark.skipif(not SCUBIEE.exists(), reason="scubiee fixture not installed under testdata/")
def test_scubiee_parse_and_determinism():
    a, b = assert_deterministic(SCUBIEE)
    assert a.stats["file_count"] >= 10
    assert a.stats["callable_count"] >= 1
    assert a.canonical_json(structural_only=True) == b.canonical_json(structural_only=True)


@pytest.mark.slow
@pytest.mark.skipif(not SCUBIEE.exists(), reason="scubiee fixture not installed under testdata/")
def test_scubiee_bakeoff(tmp_path):
    report = run_bakeoff(SCUBIEE, out_dir=tmp_path / "scubiee")
    assert report["winner_parser"] == "graphify"
    assert report["graphify"]["file_count"] >= 10
