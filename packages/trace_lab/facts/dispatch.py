"""Dispatch / override edges from simulated LSP index."""

from __future__ import annotations

from trace_lab.facts.call_graph import edges_from_dispatch
from trace_lab.lsp_index import LspIndex


def build_dispatch_edges(lsp: LspIndex):
    return edges_from_dispatch(lsp)
