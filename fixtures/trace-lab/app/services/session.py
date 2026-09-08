"""User session helper. Not on the authenticate execution path."""


def start(user_id: str) -> dict:
    return {"user": user_id, "status": "active"}
