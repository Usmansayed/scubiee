"""Virus/malware scan stub."""

from app.utils.logger import log


def scan(blob: bytes) -> None:
    if b"EVIL" in blob:
        raise ValueError("malware")
    log("scan-ok")
