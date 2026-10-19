"""Record schema. Method name is lookup, not find_user."""


class User:
    def __init__(self, key: str, name: str) -> None:
        self.key = key
        self.name = name

    @classmethod
    def lookup(cls, db: dict, key: str) -> dict:
        row = db["users"].get(key)
        if row is None:
            return {}
        return dict(row)
