"""Name-to-callable table. bind/lookup are generic on purpose."""

HANDLERS: dict[str, object] = {}


def bind(name: str, fn: object) -> None:
    HANDLERS[name] = fn


def lookup(name: str):
    return HANDLERS[name]
