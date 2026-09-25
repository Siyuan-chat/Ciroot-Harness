"""Offline contract tests for bounded GUI API conversation planning."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from fastapi.testclient import TestClient

from research_harness.investigation import InvestigationError
from research_harness.gui.conversation_model_api import plan
from research_harness.gui.help import HelpLibrary


def _config():
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    runtime = json.loads((source / "synthetic-runtime.json").read_text(encoding="utf-8"))
    runtime.update(mode="api", allow_network=True, model_api={"provider": "openai", "model": "unit-model", "api_key_env": "OPENAI_API_KEY", "max_output_tokens": 120, "timeout_seconds": 5})
    runtime["budget"]["max_model_calls"] = 3
    return {"provider": "openai", "model": "unit-model", "max_planning_calls": 2, "max_output_tokens": 120,
            "timeout_seconds": 5, "total_model_calls": 3, "runtime_template": runtime}


def _spec():
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    return json.loads((source / "synthetic-spec.json").read_text(encoding="utf-8"))


def test_api_conversation_persists_budgeted_plan_and_never_replays_unknown_call(tmp_path, monkeypatch):
    import research_harness.gui.app as gui
    calls = []

    def fake_plan(config, content):
        assert config["api_key"] == "session-only-key"
        assert "session-only-key" not in content
        calls.append(content)
        return {"kind": "research_plan", "research_spec": _spec(), "runtime": copy.deepcopy(config["runtime_template"])}, {"input_tokens": 2, "output_tokens": 3}

    monkeypatch.setattr(gui, "plan_conversation", fake_plan)
    app = gui.create_app(tmp_path, token="t")
    headers = {"x-session-token": "t"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        made = client.post("/api/v1/conversations", json={"executor": "api", "api_config": _config()}, headers={**headers, "idempotency-key": "create"})
        assert made.status_code == 200, made.text
        ident = made.json()["conversation_id"]
        waiting = client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "missing", "content": "plan this"}, headers=headers)
        assert waiting.json()["conversation"]["status"] == "waiting_credentials" and calls == []
        assert client.post("/api/v1/model-credentials/openai", json={"api_key": "session-only-key"}, headers=headers).status_code == 200
        ready = client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "plan-1", "content": "plan this"}, headers=headers).json()["conversation"]
        assert ready["status"] == "ready" and calls == ["plan this"]
        assert ready["api"]["remaining_model_calls"] == 2 and ready["api"]["usage"] == "known"
        assert ready["api"]["provider"] == "openai"
        replay = client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "plan-1", "content": "plan this"}, headers=headers)
        assert replay.status_code == 200 and calls == ["plan this"]

    # A request with an unknown outcome is stored and, after restart, is never charged again.
    failed_app = gui.create_app(tmp_path / "failed", token="t")
    monkeypatch.setattr(gui, "plan_conversation", lambda *_: (_ for _ in ()).throw(InvestigationError("RH_MODEL_NETWORK", "offline")))
    with TestClient(failed_app, base_url="http://127.0.0.1") as client:
        made = client.post("/api/v1/conversations", json={"executor": "api", "api_config": _config()}, headers={**headers, "idempotency-key": "create-2"})
        ident = made.json()["conversation_id"]
        client.post("/api/v1/model-credentials/openai", json={"api_key": "session-only-key"}, headers=headers)
        assert client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "unknown", "content": "one call"}, headers=headers).json()["conversation"]["status"] == "planning_failed"
    restarted = gui.create_app(tmp_path / "failed", token="new")
    with TestClient(restarted, base_url="http://127.0.0.1") as client:
        client.post("/api/v1/model-credentials/openai", json={"api_key": "session-only-key"}, headers={"x-session-token": "new"})
        replay = client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "unknown", "content": "one call"}, headers={"x-session-token": "new"})
        assert replay.status_code == 200 and replay.json()["conversation"]["api"]["usage"] == "UNKNOWN"


def test_api_conversation_rejects_model_scope_expansion(tmp_path, monkeypatch):
    import research_harness.gui.app as gui
    monkeypatch.setattr(gui, "plan_conversation", lambda config, content: ({"kind": "research_plan", "research_spec": _spec(), "runtime": {**config["runtime_template"], "data_mode": "live"}}, {"input_tokens": 1, "output_tokens": 1}))
    app = gui.create_app(tmp_path, token="t")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        headers = {"x-session-token": "t"}
        ident = client.post("/api/v1/conversations", json={"executor": "api", "api_config": _config()}, headers={**headers, "idempotency-key": "create"}).json()["conversation_id"]
        client.post("/api/v1/model-credentials/openai", json={"api_key": "session-only-key"}, headers=headers)
        response = client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "scope", "content": "try live"}, headers=headers)
        assert response.status_code == 200
        value = response.json()["conversation"]
        assert value["status"] == "planning_failed" and value["api"]["usage"] == "UNKNOWN"


def test_planning_adapter_uses_fake_http_only():
    config = _config()
    config["api_key"] = "session-only-key"
    config["help_context"] = HelpLibrary().search("外部 Agent 交接")
    config["dynamic_context"] = {"workspace": {"id": "w-test"}, "model_accounting": {"used_calls": 1, "remaining_calls": 4}, "authorization": {"data_mode": "synthetic", "allow_network": True}}
    observed = []

    class Reply:
        status_code = 200

        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"research_spec": _spec(), "runtime": _config()["runtime_template"]})}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3}}

    def fake_post(url, *, headers, json, timeout, allow_redirects):
        observed.append((url, headers, json, timeout, allow_redirects))
        return Reply()

    result, usage = plan(config, "offline fixture input", post=fake_post)
    assert result["research_spec"] == _spec() and result["runtime"]["data_mode"] == "synthetic" and usage == {"input_tokens": 2, "output_tokens": 3}
    assert observed[0][0] == "https://api.openai.com/v1/chat/completions"
    assert observed[0][1]["authorization"] == "Bearer session-only-key" and "session-only-key" not in str(observed[0][2])
    assert "explicit execution action" in observed[0][2]["messages"][0]["content"]
    # Provider wire format carries our structured request inside a user message;
    # custom top-level fields are not part of OpenAI's request schema.
    request_context = json.loads(observed[0][2]["messages"][1]["content"])
    assert config["help_context"][0]["source_id"] == request_context["help_context"][0]["source_id"]
    assert request_context["dynamic_context"] == config["dynamic_context"]
    assert "session-only-key" not in str(request_context["dynamic_context"])


def test_executor_switch_to_api_requires_non_expanding_config_and_keeps_accounting(tmp_path, monkeypatch):
    import research_harness.gui.app as gui
    calls = []

    def fake_plan(config, content):
        calls.append(content)
        return {"kind": "research_plan", "research_spec": _spec(), "runtime": copy.deepcopy(config["runtime_template"])}, {"input_tokens": 2, "output_tokens": 3}

    monkeypatch.setattr(gui, "plan_conversation", fake_plan)
    with TestClient(gui.create_app(tmp_path, token="t"), base_url="http://127.0.0.1") as client:
        headers = {"x-session-token": "t"}
        ident = client.post("/api/v1/conversations", json={"executor": "api", "api_config": _config()}, headers={**headers, "idempotency-key": "create"}).json()["conversation_id"]
        client.post("/api/v1/model-credentials/openai", json={"api_key": "session-only-key"}, headers=headers)
        planned = client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "plan", "content": "preserve"}, headers=headers).json()["conversation"]
        assert planned["api"]["remaining_model_calls"] == 2 and calls == ["preserve"]
        external = client.post(f"/api/v1/conversations/{ident}/executor", json={"executor": "external"}, headers={**headers, "idempotency-key": "to-external"})
        assert external.status_code == 200 and external.json()["conversation"]["api"]["remaining_model_calls"] == 2
        returned = client.post(f"/api/v1/conversations/{ident}/executor", json={"executor": "api", "api_config": _config()}, headers={**headers, "idempotency-key": "to-api"})
        assert returned.status_code == 200
        value = returned.json()["conversation"]
        assert value["executor"] == "api" and value["api"]["remaining_model_calls"] == 2
        assert "preserve" in [item["content"] for item in client.get(f"/api/v1/conversations/{ident}", headers=headers).json()["conversation"]["messages"]]
        expanded = _config()
        expanded["total_model_calls"] = 4
        expanded["max_planning_calls"] = 3
        expanded["runtime_template"]["budget"]["max_model_calls"] = 4
        denied = client.post(f"/api/v1/conversations/{ident}/executor", json={"executor": "api", "api_config": expanded}, headers={**headers, "idempotency-key": "expand"})
        assert denied.status_code == 409 and denied.json()["code"] == "RH_GUI_API_CONFIG_EXPANSION"
        assert client.post(f"/api/v1/conversations/{ident}/executor", json={"executor": "api"}, headers={**headers, "idempotency-key": "missing"}).status_code == 400


def test_help_library_control_is_isolated_and_api_planning_receives_matched_passages(tmp_path, monkeypatch):
    import research_harness.gui.app as gui
    captured = []
    monkeypatch.setattr(gui, "plan_conversation", lambda config, content: (captured.append(config) or ({"kind": "research_plan", "research_spec": _spec(), "runtime": copy.deepcopy(config["runtime_template"])}, {"input_tokens": 1, "output_tokens": 1})))
    with TestClient(gui.create_app(tmp_path, token="t"), base_url="http://127.0.0.1") as client:
        headers = {"x-session-token": "t"}
        control = {"actor": "test-agent", "request_id": "help-1", "scope": {"workspace_id": "default", "library_id": "default", "collection_id": "all"}, "payload": {"query": "外部 Agent 交接"}}
        found = client.post("/api/v1/control", json={"action": "help.search", **control}, headers=headers)
        assert found.status_code == 200 and found.json()["items"]
        source_id = found.json()["items"][0]["source_id"]
        read = client.post("/api/v1/control", json={"action": "help.read", **{**control, "request_id": "help-2", "payload": {"source_id": source_id}}}, headers=headers)
        assert read.json()["item"]["source_id"] == source_id and "conversation.list_pending" in read.json()["item"]["text"]
        assert not (tmp_path / "rag.sqlite").exists()
        ident = client.post("/api/v1/conversations", json={"executor": "api", "api_config": _config()}, headers={**headers, "idempotency-key": "create-help"}).json()["conversation_id"]
        client.post("/api/v1/model-credentials/openai", json={"api_key": "session-only-key"}, headers=headers)
        planned = client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "plan-help", "content": "如何让外部 Agent 交接？"}, headers=headers)
        assert planned.json()["conversation"]["status"] == "ready"
        assert captured[0]["help_context"] and captured[0]["help_context"][0]["source"].endswith("external_agent_handoff_skill.md")


def test_help_library_understands_chinese_workspace_questions_and_planning_uses_result(tmp_path, monkeypatch):
    import research_harness.gui.app as gui
    library = HelpLibrary()
    for question in ("怎么在GUI新建文献库", "如何创建工作区和空库"):
        matches = library.search(question)
        assert matches and matches[0]["source"] == "workspace_empty_library_skill.md"
        assert matches[0]["paragraph"] >= 1 and matches[0]["source_id"].startswith("help/")
    captured = []
    monkeypatch.setattr(gui, "plan_conversation", lambda config, content: (captured.append(config) or ({"kind": "research_plan", "research_spec": _spec(), "runtime": copy.deepcopy(config["runtime_template"])}, {"input_tokens": 1, "output_tokens": 1})))
    with TestClient(gui.create_app(tmp_path, token="t"), base_url="http://127.0.0.1") as client:
        headers = {"x-session-token": "t"}
        ident = client.post("/api/v1/conversations", json={"executor": "api", "api_config": _config()}, headers={**headers, "idempotency-key": "create-chinese-help"}).json()["conversation_id"]
        client.post("/api/v1/model-credentials/openai", json={"api_key": "session-only-key"}, headers=headers)
        assert client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "plan-chinese-help", "content": "怎么在GUI新建文献库"}, headers=headers).json()["conversation"]["status"] == "ready"
        assert captured[0]["help_context"][0]["source"] == "workspace_empty_library_skill.md"
        context = captured[0]["dynamic_context"]
        assert context["workspace"] == {"id": "default", "name": "Default workspace"}
        assert context["library"] == {"id": "default", "name": "Default library"}
        assert context["collection"] == {"id": "all", "name": "all"}
        assert context["conversation"] == {"executor": "api", "status": "planning"}
        assert context["model_accounting"]["used_calls"] == 1
        # _config() authorizes three total calls; this first planning turn is
        # reserved already, so server context must report two remaining.
        assert context["model_accounting"]["remaining_calls"] == 2
        assert context["authorization"]["data_mode"] == "synthetic"
        assert "api_key" not in str(context) and "session-only-key" not in str(context)


def test_api_help_answer_persists_citations_and_can_continue_to_a_research_plan(tmp_path, monkeypatch):
    import research_harness.gui.app as gui
    captured = []

    def fake_plan(config, content):
        captured.append(config)
        if len(captured) == 1:
            return {"kind": "help_answer", "help_answer": {"content": "请用 workspace.create 创建工作区；空库尚未索引。", "source_ids": [config["help_context"][0]["source_id"]]}}, {"input_tokens": 2, "output_tokens": 3}
        return {"kind": "research_plan", "research_spec": _spec(), "runtime": copy.deepcopy(config["runtime_template"])}, {"input_tokens": 2, "output_tokens": 3}

    monkeypatch.setattr(gui, "plan_conversation", fake_plan)
    with TestClient(gui.create_app(tmp_path, token="t"), base_url="http://127.0.0.1") as client:
        headers = {"x-session-token": "t"}
        ident = client.post("/api/v1/conversations", json={"executor": "api", "api_config": _config()}, headers={**headers, "idempotency-key": "create-help-answer"}).json()["conversation_id"]
        client.post("/api/v1/model-credentials/openai", json={"api_key": "session-only-key"}, headers=headers)
        answer = client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "help", "content": "怎么在GUI新建文献库"}, headers=headers).json()["conversation"]
        assert answer["status"] == "awaiting_input" and answer["run_id"] is None
        reply = next(item for item in answer["messages"] if item["role"] == "assistant")
        assert reply["refs"]["help_source_ids"] == [captured[0]["help_context"][0]["source_id"]]
        assert client.post(f"/api/v1/conversations/{ident}/execute", json={}, headers={**headers, "idempotency-key": "cannot-execute-help"}).status_code == 409
        planned = client.post(f"/api/v1/conversations/{ident}/turns", json={"request_id": "research", "content": "现在形成研究计划"}, headers=headers).json()["conversation"]
        assert planned["status"] == "ready" and any(item["content"] == "请用 workspace.create 创建工作区；空库尚未索引。" for item in captured[1]["conversation_history"])
