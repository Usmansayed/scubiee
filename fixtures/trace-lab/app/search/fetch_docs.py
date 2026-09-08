"""Fetch documents for ranked hits."""

from app.config.database import connect
from app.http.client import get


def fetch_docs(ranked: list) -> list:
    db = connect()
    out = []
    for hit in ranked:
        remote = get("/doc", {"tok": hit["tok"]})
        out.append({"hit": hit, "db": db, "remote": remote})
    return out
