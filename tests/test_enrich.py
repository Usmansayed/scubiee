import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from enrich import chunk_repo_from_ir, enrich_repo, inject_metadata
from metadata import build_chunk_meta
from parse_harness.graphify_adapter import parse_with_graphify

FIXTURE = ROOT / "fixtures" / "mini-repo"
SCUBIEE = ROOT / "testdata" / "scubiee-news-flow"


def test_metadata_for_login_is_deterministic_and_useful():
    ir = parse_with_graphify(FIXTURE, parallel=False)
    a = build_chunk_meta(ir, "auth/login.ts", start_line=4, end_line=8)
    b = build_chunk_meta(ir, "auth/login.ts", start_line=4, end_line=8)
    assert a == b
    assert a.repository == "mini-repo"
    assert a.module == "auth"
    assert a.folder == "auth"
    assert "login" in a.functions
    assert "validatePassword" in a.imports
    assert "createJWT" in a.imports
    assert "login" in a.exports
    text = a.render()
    assert "Repository: mini-repo" in text
    assert "--------------------------------" in text


def test_injection_preserves_original_and_prepends_metadata():
    ir = parse_with_graphify(FIXTURE, parallel=False)
    chunks = chunk_repo_from_ir(ir, FIXTURE)
    login_chunks = [c for c in chunks if c.file == "auth/login.ts" and c.symbol == "login"]
    assert login_chunks
    enriched = inject_metadata(login_chunks[0], ir)
    assert enriched.original == login_chunks[0].content
    assert enriched.enriched.startswith("Repository: mini-repo")
    assert enriched.enriched.endswith(enriched.original) or enriched.original in enriched.enriched
    assert "function login" in enriched.enriched or "export function login" in enriched.enriched
    # Boundary unchanged: same start/end lines
    assert enriched.start_line == login_chunks[0].start_line
    assert enriched.end_line == login_chunks[0].end_line


def test_enrich_repo_fixture_counts():
    ir = parse_with_graphify(FIXTURE, parallel=False)
    enriched = enrich_repo(ir, FIXTURE)
    assert len(enriched) >= 6  # 6 functions (+ optional preambles)
    assert all(e.enriched.startswith("Repository:") for e in enriched)
    # Related sibling: validate.ts next to login.ts
    login = next(e for e in enriched if e.symbol == "login")
    assert "auth/validate.ts" in login.metadata.related_files


@pytest.mark.skipif(not SCUBIEE.exists(), reason="scubiee fixture not installed under testdata/")
def test_scubiee_enrich_smoke():
    ir = parse_with_graphify(SCUBIEE, parallel=False)
    enriched = enrich_repo(ir, SCUBIEE)
    assert len(enriched) >= 20
    sample = enriched[0]
    assert "Repository: scubiee-news-flow" in sample.enriched
    assert "--------------------------------" in sample.enriched
    assert len(sample.enriched) > len(sample.original)
