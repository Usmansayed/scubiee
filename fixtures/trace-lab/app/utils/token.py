"""Generic decoder. Names and comments stay non-specific on purpose."""


def decode(value: str) -> dict:
    parts = value.split(".", 2)
    if len(parts) != 3:
        return {"sub": value, "age": 0}
    return {"sub": parts[0], "age": int(parts[1] or 0)}
