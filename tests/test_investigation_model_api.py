import json as json_module

import pytest

from research_harness.investigation import InvestigationError, InvestigationService
from research_harness.investigation_contracts import validate_runtime
from research_harness.investigation_model_api import advance_api_run, run_model_task
from test_investigation_c1 import SPEC, SCENARIO, answer


def runtime(provider):
    return {"mode": "api", "data_mode": "synthetic", "allow_network": True,
            "model_api": {"provider": provider, "model": "test-model", "api_key_env": "TEST_RESEARCH_MODEL_KEY", "max_output_tokens": 1024, "timeout_seconds": 10},
            "budget": {"max_tasks": 10, "max_model_calls": 10}}


class Reply:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


@pytest.mark.parametrize("provider,host,token_field", [
    ("openai", "api.openai.com", "max_completion_tokens"),
    ("anthropic", "api.anthropic.com", "max_tokens"),
    ("deepseek", "api.deepseek.com", "max_tokens"),
    ("qwen", "dashscope-intl.aliyuncs.com", "max_tokens"),
    ("kimi", "api.moonshot.ai", "max_tokens"),
])
def test_provider_protocol_and_model_task_contract(tmp_path, monkeypatch, provider, host, token_field):
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    config = runtime(provider)
    validate_runtime(config)
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, config, SCENARIO)["run_id"]
        task = service.get_pending_tasks(run)[0]
        def fake_post(url, *, headers, json, timeout, allow_redirects):
            body = json
            assert host in url and url.startswith("https://") and not allow_redirects
            assert body["model"] == "test-model" and body[token_field] == 1024
            assert timeout == 10
            assert "private-test-key" in str(headers) and "private-test-key" not in str(body)
            if provider == "anthropic":
                assert body["tools"][0]["input_schema"] == task["output_schema"]
                return Reply({"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "submit_result", "input": answer(task)}], "usage": {"input_tokens": 10, "output_tokens": 5}})
            if provider == "kimi":
                assert "response_format" not in body
            else:
                assert body["response_format"] == {"type": "json_object"}
            return Reply({"choices": [{"finish_reason": "stop", "message": {"content": json_module.dumps(answer(task))}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        assert run_model_task(service, run, task, post=fake_post)["status"] == "accepted"
        assert service.status(run)["budget"]["reserved_model_calls"] == 1
        assert service.db.execute("SELECT status FROM model_api_calls").fetchone()[0] == "accepted"


def test_api_runner_completes_synthetic_chain_and_reopens_without_new_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    calls = []
    def fake_post(url, *, headers, json, timeout, allow_redirects):
        task = json_module.loads(json["messages"][1]["content"])
        calls.append(task["role"])
        result = answer({"role": task["role"], "payload": task["payload"]})
        return Reply({"choices": [{"finish_reason": "stop", "message": {"content": json_module.dumps(result)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    config = runtime("deepseek")
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, config, SCENARIO)["run_id"]
        first = service.get_pending_tasks(run)[0]
        with pytest.raises(InvestigationError):
            service.reserve_model_call(run, first["task_id"], first["task_version"] + 1)
        result = advance_api_run(service, run, post=fake_post)
        assert result["status"] == "partial" and result["stage"] == "completed"
        assert service.get_artifacts(run)
        used = service.status(run)["budget"]["reserved_model_calls"]
        assert used == len(calls) == 8
        assert all(row[0] == "accepted" for row in service.db.execute("SELECT status FROM model_api_calls"))
        assert {issue["code"] for issue in service.get_result(run)["issues"]} >= {"RH_SECTION_DRAFT", "RH_SECTION_TITLE_DRAFT"}
    with InvestigationService(tmp_path) as service:
        assert advance_api_run(service, run, post=fake_post)["status"] == "partial"
        assert service.status(run)["budget"]["reserved_model_calls"] == used == len(calls)


def test_api_failure_reserves_call_before_request_and_keeps_task(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    config = runtime("openai")
    config["budget"]["max_model_calls"] = 1
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, config, SCENARIO)["run_id"]
        fail_response = lambda *args, **kwargs: type("Failure", (), {"status_code": 429})()
        with pytest.raises(InvestigationError) as exc:
            advance_api_run(service, run, post=fail_response)
        assert exc.value.code == "RH_MODEL_HTTP"
        assert service.get_pending_tasks(run)
        assert service.status(run)["budget"]["reserved_model_calls"] == 1
        assert advance_api_run(service, run, post=fail_response)["status"] == "partial"
        assert service.get_result(run)["issues"][0]["code"] == "RH_MODEL_CALL_BUDGET"
