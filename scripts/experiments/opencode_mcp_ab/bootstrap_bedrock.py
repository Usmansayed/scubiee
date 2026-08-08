"""Bootstrap Amazon Bedrock Nova Pro for OpenCode A/B (no secret printing)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "out" / "experiments" / "opencode_mcp_ab"


def main() -> None:
    text = (ROOT / ".env").read_text(encoding="utf-8")
    vals: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(aws_bedrock_api_key|aws_region)\s*=\s*(.+?)\s*$", line, re.I)
        if m:
            vals[m.group(1).lower()] = m.group(2).strip().strip('"').strip("'")
    key = vals.get("aws_bedrock_api_key") or ""
    region = vals.get("aws_region") or "eu-central-1"
    if len(key) < 20:
        raise SystemExit("missing aws_bedrock_api_key in .env")
    print("bedrock_key_len", len(key), "region", region)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ".bedrock.json").write_text(
        json.dumps({"key": key, "region": region}, indent=2) + "\n", encoding="utf-8"
    )
    # EU region → prefer EU inference profile for Nova Pro.
    model_id = (
        "eu.amazon.nova-pro-v1:0"
        if region.startswith("eu-")
        else "amazon.nova-pro-v1:0"
    )
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "amazon-bedrock": {
                "options": {"region": region},
                "models": {
                    model_id: {
                        "name": "Amazon Nova Pro",
                        "limit": {"context": 300000, "output": 8192},
                    },
                    "amazon.nova-pro-v1:0": {
                        "name": "Amazon Nova Pro (base)",
                        "limit": {"context": 300000, "output": 8192},
                    },
                    "eu.amazon.nova-pro-v1:0": {
                        "name": "Amazon Nova Pro (EU)",
                        "limit": {"context": 300000, "output": 8192},
                    },
                },
            }
        },
    }
    (OUT / "opencode_bedrock.json").write_text(
        json.dumps(cfg, indent=2) + "\n", encoding="utf-8"
    )
    print("wrote", OUT / "opencode_bedrock.json", "preferred_model", model_id)


if __name__ == "__main__":
    main()
