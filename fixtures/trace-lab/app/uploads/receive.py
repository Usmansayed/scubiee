"""Upload receive pipeline."""

from app.notify.mailer import send
from app.uploads.index_file import index_file
from app.uploads.scan import scan
from app.uploads.store import store


def receive(blob: bytes, user: str) -> dict:
    scan(blob)
    path = store(blob, user)
    meta = index_file(path)
    send(user, "uploaded")
    return meta
