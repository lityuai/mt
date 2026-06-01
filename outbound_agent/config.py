from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LLM_CONFIG_PATH = ROOT / "config" / "llm.json"


def load_llm_config(path: str | Path | None = None) -> dict[str, str]:
    config_path = Path(
        os.getenv("OUTBOUND_AGENT_LLM_CONFIG") or path or DEFAULT_LLM_CONFIG_PATH
    )
    data: dict[str, Any] = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM config JSON is invalid: {config_path}") from exc

    return {
        "api_key": str(data.get("api_key") or os.getenv("OPENAI_API_KEY") or "").strip(),
        "base_url": str(
            data.get("base_url")
            or data.get("api_url")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).strip(),
        "model": str(data.get("model") or os.getenv("OPENAI_MODEL") or "").strip(),
        "path": str(config_path),
    }


def public_llm_config(path: str | Path | None = None) -> dict[str, Any]:
    config = load_llm_config(path)
    return {
        "configured": bool(config["api_key"] and config["model"]),
        "has_api_key": bool(config["api_key"]),
        "base_url": config["base_url"],
        "model": config["model"],
        "path": config["path"],
    }
