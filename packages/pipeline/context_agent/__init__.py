"""Context Agent — Qwen3-1.7B via llama.cpp as retrieval orchestrator.

Not a coder. Calls CE/Graphify tools, returns a structured context pack
for the main coding agent.
"""

from __future__ import annotations

from pipeline.context_agent.agent import gather_context, run_cli

__all__ = ["gather_context", "run_cli"]
