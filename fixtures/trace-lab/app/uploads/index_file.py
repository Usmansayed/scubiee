"""Index stored upload for search."""

from app.search.tokenize import tokenize_q


def index_file(path: str) -> dict:
    return {"path": path, "toks": tokenize_q(path)}
