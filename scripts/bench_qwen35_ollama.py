"""Benchmark Ollama qwen3.5:0.8b tok/s (think off)."""
from __future__ import annotations

import json
import urllib.request

payload = {
    "model": "qwen3.5-0.8b-q4",
    "prompt": "Write one short sentence about tea. No preamble.",
    "stream": False,
    "think": False,
    "options": {
        "num_predict": 80,
        "temperature": 0,
        "num_gpu": 99,
        "num_ctx": 2048,
    },
}

req = urllib.request.Request(
    "http://127.0.0.1:11434/api/generate",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=180) as resp:
    d = json.loads(resp.read().decode("utf-8"))

eval_count = d.get("eval_count") or 0
eval_ns = d.get("eval_duration") or 1
prompt_count = d.get("prompt_eval_count") or 0
prompt_ns = d.get("prompt_eval_duration") or 1
print("response:", (d.get("response") or "")[:240].replace("\n", " "))
print(f"eval_count={eval_count}")
print(f"eval_tok_s={eval_count / (eval_ns / 1e9):.2f}")
print(f"prompt_tok_s={prompt_count / (prompt_ns / 1e9):.2f}")
print(f"load_s={(d.get('load_duration') or 0) / 1e9:.2f}")
print(f"total_s={(d.get('total_duration') or 0) / 1e9:.2f}")
print("done_reason:", d.get("done_reason"))
