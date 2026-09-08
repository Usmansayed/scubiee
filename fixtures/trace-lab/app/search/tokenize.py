"""Query tokenization."""


def tokenize_q(text: str) -> list:
    return [t for t in text.lower().split() if t]
