"""Shared validation and endpoint policy for model provider profiles."""
from __future__ import annotations

from urllib.parse import urlsplit

from .errors import ValidationError

ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
    "kimi": "https://api.moonshot.ai/v1/chat/completions",
}


def validate_profile(config: dict) -> dict:
    if not isinstance(config, dict) or config.get("provider") not in {*ENDPOINTS, "openai_compatible"}:
        raise ValidationError("unsupported model provider")
    if not isinstance(config.get("model"), str) or not config["model"].strip():
        raise ValidationError("model name is required")
    endpoint = config.get("endpoint") or ENDPOINTS.get(config["provider"])
    if config["provider"] == "openai_compatible" and not config.get("endpoint"):
        raise ValidationError("OpenAI-compatible provider requires an explicit endpoint")
    local = config.get("profile") == "local"
    parsed = urlsplit(endpoint or "")
    if local:
        if config["provider"] not in {"openai_compatible", "openai"} or parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValidationError("local model profile must use HTTP on a loopback address")
        if config.get("api_key_env"):
            raise ValidationError("local model profile must not configure an API key")
    else:
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValidationError("cloud model endpoint must be HTTPS without credentials or query")
        if not isinstance(config.get("api_key_env"), str) or not config["api_key_env"]:
            raise ValidationError("cloud model profile requires an API key environment variable")
    return {"provider": config["provider"], "model": config["model"], "endpoint": endpoint, "local": local}
