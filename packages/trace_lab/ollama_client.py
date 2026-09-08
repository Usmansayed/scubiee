"""Minimal Ollama generate client for Trace Director bakeoff."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class OllamaResult:
    text: str
    eval_count: int
    eval_duration_ns: int
    prompt_eval_count: int
    prompt_eval_duration_ns: int
    load_duration_ns: int
    total_duration_ns: int
    wall_s: float
    raw: dict[str, Any]

    @property
    def eval_tok_s(self) -> float:
        if self.eval_duration_ns <= 0:
            return 0.0
        return self.eval_count / (self.eval_duration_ns / 1e9)

    @property
    def prompt_tok_s(self) -> float:
        if self.prompt_eval_duration_ns <= 0:
            return 0.0
        return self.prompt_eval_count / (self.prompt_eval_duration_ns / 1e9)


def ollama_generate(
    prompt: str,
    *,
    model: str = "qwen3.5-0.8b-q4",
    host: str = "http://127.0.0.1:11434",
    system: str | None = None,
    num_predict: int = 160,
    temperature: float = 0.0,
    num_ctx: int = 8192,
    keep_alive: str = "30m",
    timeout_s: float = 120.0,
) -> OllamaResult:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "keep_alive": keep_alive,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
            "num_gpu": 99,
            "num_ctx": num_ctx,
        },
    }
    if system:
        payload["system"] = system
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"ollama generate failed: {e}") from e
    wall = time.perf_counter() - t0
    return OllamaResult(
        text=(raw.get("response") or "").strip(),
        eval_count=int(raw.get("eval_count") or 0),
        eval_duration_ns=int(raw.get("eval_duration") or 0),
        prompt_eval_count=int(raw.get("prompt_eval_count") or 0),
        prompt_eval_duration_ns=int(raw.get("prompt_eval_duration") or 0),
        load_duration_ns=int(raw.get("load_duration") or 0),
        total_duration_ns=int(raw.get("total_duration") or 0),
        wall_s=wall,
        raw=raw,
    )
