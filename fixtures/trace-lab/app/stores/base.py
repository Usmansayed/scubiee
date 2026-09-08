"""Abstract record store."""


class Store:
    def fetch(self, key: str) -> dict:
        raise NotImplementedError
