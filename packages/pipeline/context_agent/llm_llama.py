"""OpenAI-compatible chat client for llama.cpp server (Vulkan Qwen)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


def llama_base_url() -> str:
    return (
        os.environ.get("CTX_LLAMA_URL")
        or os.environ.get("LLAMA_SERVER_URL")
        or "http://127.0.0.1:8080"
    ).rstrip("/")


def llama_model() -> str:
    # llama-server often ignores model name; keep a stable id for logs.
    return os.environ.get("CTX_LLAMA_MODEL") or "Qwen3-1.7B-Q4_K_M"


class LlamaCppClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        model: str | None = None,
        timeout: float = 180.0,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ):
        self.base = (base_url or llama_base_url()).rstrip("/")
        self.model = model or llama_model()
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

    def healthy(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{self.base}/health",
                headers={"Accept": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001
            try:
                req = urllib.request.Request(
                    f"{self.base}/v1/models",
                    headers={"Accept": "application/json"},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    return resp.status == 200
            except Exception:  # noqa: BLE001
                return False

    def chat(self, messages: list[dict[str, str]]) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
            # Qwen3: disable thinking budget when supported by server/template
            "chat_template_kwargs": {"enable_thinking": False},
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/v1/chat/completions",
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"llama.cpp HTTP {exc.code}: {err[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"llama.cpp unreachable at {self.base}: {exc.reason}. "
                "Start: scripts/context_agent/start_llama_qwen.ps1"
            ) from exc

        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"llama.cpp empty choices: {payload!r}"[:400])
        msg = choices[0].get("message") or {}
        content = msg.get("content") or ""
        # Some Qwen builds put reasoning in a separate field
        if not content and msg.get("reasoning_content"):
            content = str(msg.get("reasoning_content"))
        return str(content).strip()
