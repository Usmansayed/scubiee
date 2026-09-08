"""Symbol index helpers over TraceNode corpus."""

from __future__ import annotations

from trace_lab.types import TraceNode


def by_file(nodes: dict[str, TraceNode]) -> dict[str, list[TraceNode]]:
    out: dict[str, list[TraceNode]] = {}
    for n in nodes.values():
        out.setdefault(n.file, []).append(n)
    for group in out.values():
        group.sort(key=lambda n: n.start_line)
    return out


def covering(nodes: dict[str, TraceNode], file: str, line: int) -> TraceNode | None:
    file = file.replace("\\", "/")
    hits = [
        n
        for n in nodes.values()
        if n.file == file and n.start_line <= line <= n.end_line and n.kind != "class"
    ]
    if not hits:
        return None
    hits.sort(key=lambda n: (n.end_line - n.start_line, n.start_line))
    return hits[0]
