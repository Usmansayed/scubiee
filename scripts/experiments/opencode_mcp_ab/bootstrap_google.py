"""Bootstrap Google AI Studio keys for OpenCode A/B (do not print secrets)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "out" / "experiments" / "opencode_mcp_ab"


def load_google_keys() -> list[str]:
    text = (ROOT / ".env").read_text(encoding="utf-8")
    keys: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(GOOGLE[123])\s*=\s*(.+?)\s*$", line)
        if not m:
            continue
        keys[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    ordered = [keys[k] for k in ("GOOGLE1", "GOOGLE2", "GOOGLE3") if k in keys and keys[k]]
    if not ordered:
        raise SystemExit("No GOOGLE1/2/3 keys found in .env")
    return ordered


def main() -> None:
    keys = load_google_keys()
    print("loaded_keys", len(keys), "lens", [len(k) for k in keys])

    auth_dir = Path.home() / ".local" / "share" / "opencode"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_path = auth_dir / "auth.json"
    auth: dict = {}
    if auth_path.is_file():
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            auth = {}
    auth["google"] = {"type": "api", "key": keys[0]}
    auth_path.write_text(json.dumps(auth, indent=2) + "\n", encoding="utf-8")
    print("wrote", auth_path, "google.type=api")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ".google_keys.json").write_text(
        json.dumps({"keys": keys, "i": 0}, indent=2) + "\n", encoding="utf-8"
    )
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "google": {
                "npm": "@ai-sdk/google",
                "name": "Google AI Studio",
                "options": {"apiKey": keys[0]},
                "models": {
                    "gemini-3.1-pro-preview": {"name": "Gemini 3.1 Pro Preview"},
                    "gemini-2.5-pro": {"name": "Gemini 2.5 Pro"},
                    "gemini-2.5-flash": {"name": "Gemini 2.5 Flash"},
                },
            }
        },
    }
    cfg_path = OUT / "opencode_google.json"
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print("wrote", cfg_path)


if __name__ == "__main__":
    main()
