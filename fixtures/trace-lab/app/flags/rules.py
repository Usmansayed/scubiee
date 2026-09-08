"""Local rule matching."""


def match(rules: dict, user: str) -> bool:
    allow = rules.get("allow") or []
    return user in allow or bool(rules.get("default"))
