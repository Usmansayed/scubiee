"""Session helpers for the CE sim fixture."""


def start_session(user: str) -> dict:
    return {"user": user, "status": "active"}


def end_session(session: dict) -> dict:
    session = dict(session)
    session["status"] = "closed"
    return session
