"""SEIR — embedding-oriented intermediate representations (experiment only)."""

from seir.render import ARMS, render
from seir.spans import iter_python_spans
from seir.types import SpanContext

__all__ = ["ARMS", "SpanContext", "iter_python_spans", "render"]
