"""Search entry."""

from app.search.fetch_docs import fetch_docs
from app.search.rank import rank
from app.search.tokenize import tokenize_q


def query(text: str) -> list:
    toks = tokenize_q(text)
    ranked = rank(toks)
    return fetch_docs(ranked)
