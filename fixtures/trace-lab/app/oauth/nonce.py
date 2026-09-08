"""Nonce stamping used by rotate."""


def stamp(token: str) -> str:
    return "n:" + token
