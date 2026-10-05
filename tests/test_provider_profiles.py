import pytest

from research_harness.errors import ValidationError
from research_harness.provider_profiles import validate_profile
from research_harness.investigation_model_api import _request


@pytest.mark.parametrize("provider", ["openai", "anthropic", "deepseek", "qwen", "kimi"])
def test_legacy_cloud_profiles_remain_valid(provider):
    result = validate_profile({"provider": provider, "model": "model-x", "api_key_env": "MODEL_KEY"})
    assert result["endpoint"].startswith("https://") and not result["local"]


def test_openai_compatible_requires_explicit_https_endpoint_and_key():
    with pytest.raises(ValidationError):
        validate_profile({"provider": "openai_compatible", "model": "x", "api_key_env": "MODEL_KEY"})
    assert validate_profile({"provider": "openai_compatible", "model": "x", "api_key_env": "MODEL_KEY", "endpoint": "https://api.example.test/v1/chat/completions"})["endpoint"].startswith("https://")


@pytest.mark.parametrize("endpoint", ["http://example.com/v1", "http://localhost.evil/v1", "https://127.0.0.1/v1"])
def test_remote_or_cloud_profiles_cannot_use_local_http(endpoint):
    with pytest.raises(ValidationError):
        validate_profile({"provider": "openai_compatible", "model": "x", "profile": "local", "endpoint": endpoint})


@pytest.mark.parametrize("endpoint", ["http://localhost:1234/v1", "http://127.0.0.1:1234/v1", "http://[::1]:1234/v1"])
def test_explicit_local_profile_allows_loopback_without_key(endpoint):
    result = validate_profile({"provider": "openai_compatible", "model": "local-model", "profile": "local", "endpoint": endpoint})
    assert result["local"] and result["endpoint"] == endpoint


def test_local_profile_builds_keyless_application_request():
    runtime = {"model_api": {"provider": "openai_compatible", "model": "local-model", "profile": "local", "endpoint": "http://127.0.0.1:1234/v1/chat/completions", "max_output_tokens": 32}}
    task = {"role": "planning", "task_type": "plan", "payload": {}, "output_schema": {"type": "object"}}
    endpoint, headers, body = _request(task, runtime)
    assert endpoint.startswith("http://127.0.0.1:") and "authorization" not in headers
    assert body["model"] == "local-model"
