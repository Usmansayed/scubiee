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
