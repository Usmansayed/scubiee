"""Parse webhook body."""

import json


def parse(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8") or "{}")
