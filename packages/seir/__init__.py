"""SEIR — embedding-oriented intermediate representations (experiment only)."""

from seir.render import ARMS, MATRIX_ARMS, render
from seir.spans import CHUNK_UNITS, iter_python_spans
from seir.types import SpanContext

__all__ = [
    "ARMS",
    "CHUNK_UNITS",
    "MATRIX_ARMS",
    "SpanContext",
    "iter_python_spans",
    "render",
]
