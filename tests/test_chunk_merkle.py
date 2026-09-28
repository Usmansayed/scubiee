from pipeline.chunk_merkle import chunk_digest, diff_chunk_records
from pipeline.store import ChunkRecord


def _chunk(symbol: str, text: str, *, start: int = 1, end: int = 3) -> ChunkRecord:
    return ChunkRecord(
        id=0,
        file="pkg/example.py",
        start_line=start,
        end_line=end,
        symbol=symbol,
        text=text,
        enriched=text,
    )


def test_chunk_diff_keeps_vector_for_unchanged_symbol_despite_line_shift():
    old = [_chunk("stable", "same body", start=1, end=3), _chunk("changed", "old", start=5, end=7)]
    new = [_chunk("stable", "same body", start=10, end=12), _chunk("changed", "new", start=14, end=16)]

    diff = diff_chunk_records(old, new)

    assert diff.unchanged == {"stable"}
    assert diff.changed == {"changed"}
    assert diff.removed == set()


def test_chunk_digest_changes_when_embedding_content_changes():
    assert chunk_digest(_chunk("handler", "old")) != chunk_digest(_chunk("handler", "new"))


def test_file_wide_context_lines_do_not_mark_every_chunk_changed():
    def enriched(exports: str, imports: str, body: str) -> str:
        return (
            "File: pkg/example.py\nModule: pkg\nSymbol: handler\n"
            f"Imports: {imports}\nExports: {exports}\nFunctions: a, b\n"
            f"Dependents: x\n{body}"
        )

    before = _chunk("handler", "")
    before.enriched = enriched("a, b", "os", "def handler(): return 1")
    sibling_added = _chunk("handler", "")
    sibling_added.enriched = enriched("_new, a, b", "os, sys", "def handler(): return 1")
    body_changed = _chunk("handler", "")
    body_changed.enriched = enriched("a, b", "os", "def handler(): return 2")

    assert chunk_digest(before) == chunk_digest(sibling_added)
    assert chunk_digest(before) != chunk_digest(body_changed)


def test_longer_file_wide_lines_that_move_the_cap_do_not_re_embed():
    """Issue 5: the enriched body is capped after the file-wide lines are
    prepended, so one new export moved the cut in every chunk of the file."""
    code = "def handler(payload):\n" + "    x = payload\n" * 60 + "    return x\n"

    def rec(exports: str) -> ChunkRecord:
        body = f"Exports: {exports}\n{code}"[:512]
        return ChunkRecord(id=0, file="pkg/example.py", start_line=1, end_line=62,
                           symbol="handler", text=code[:512], enriched=body)

    before, after = rec("a, b"), rec("a, b, " + ", ".join(f"new_{i}" for i in range(30)))
    assert before.enriched != after.enriched
    assert chunk_digest(before) == chunk_digest(after)


def test_digest_is_stable_across_text_caps_of_older_builds():
    code = "def handler():\n" + "    pass\n" * 200
    old = ChunkRecord(id=0, file="pkg/example.py", start_line=1, end_line=201,
                      symbol="handler", text=code[:1200], enriched="x")
    new = ChunkRecord(id=0, file="pkg/example.py", start_line=1, end_line=201,
                      symbol="handler", text=code[:512], enriched="y")
    assert chunk_digest(old) == chunk_digest(new)
    edited = ChunkRecord(id=0, file="pkg/example.py", start_line=1, end_line=201,
                         symbol="handler", text=("def handler(a):\n" + code[15:])[:512], enriched="y")
    assert chunk_digest(edited) != chunk_digest(new)
