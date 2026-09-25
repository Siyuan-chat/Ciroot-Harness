import importlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from research_harness.investigation_model_api import run_model_task
from test_investigation_c1 import answer


def test_gui_model_key_stays_in_session_and_runs_one_bounded_task(tmp_path, monkeypatch):
    gui = importlib.import_module("research_harness.gui.app")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    body = {name: json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec", "runtime", "scenario")}
    body["runtime"].update(mode="api", allow_network=True, model_api={
        "provider": "openai", "model": "test-model", "api_key_env": "OPENAI_API_KEY",
        "max_output_tokens": 1024, "timeout_seconds": 10,
    })
    body["runtime"]["budget"]["max_model_calls"] = 1
    calls = []

    class Reply:
        status_code = 200

        def json(self):
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer(calls[-1]))}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 3}}

    def fake_post(url, *, headers, json, timeout, allow_redirects):
        assert headers["authorization"] == "Bearer private-test-key"
        assert "private-test-key" not in str(json)
        calls.append({"role": "planning", "payload": __import__("json").loads(json["messages"][1]["content"])["payload"]})
        return Reply()

    monkeypatch.setattr(gui, "run_model_task", lambda svc, run_id, task: run_model_task(svc, run_id, task, post=fake_post))
    app = gui.create_app(tmp_path, token="unit-token")
    headers = {"x-session-token": "unit-token"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/model-credentials").json()["providers"]["openai"] == "missing"
        assert client.post("/api/v1/model-credentials/openai", json={"api_key": "private-test-key"}).status_code == 403
        saved = client.post("/api/v1/model-credentials/openai", json={"api_key": "private-test-key"}, headers=headers)
        assert saved.json() == {"schema_version": "1", "context":{"workspace_id":"default","library_id":"default","collection_id":"all"}, "provider": "openai", "status": "session"}
        assert "private-test-key" not in str(client.get("/api/v1/model-credentials").json())
        assert "OPENAI_API_KEY" not in os.environ
        created = client.post("/api/v1/runs", json=body, headers={**headers, "idempotency-key": "create-api"})
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
        assert client.get(f"/api/v1/runs/{run_id}").json()["mode"] == "api"
        assert "OPENAI_API_KEY" not in os.environ
        step = client.post(f"/api/v1/runs/{run_id}/model-step", json={}, headers={**headers, "idempotency-key": "step-1"})
        assert step.status_code == 200, step.text
        assert step.json()["budget"]["reserved_model_calls"] == 1
        assert len(calls) == 1
        assert "OPENAI_API_KEY" not in os.environ
        client.delete("/api/v1/model-credentials/openai", headers=headers)
        assert client.get("/api/v1/model-credentials").json()["providers"]["openai"] == "missing"


def test_source_credentials_are_scoped_to_gui_operations(tmp_path, monkeypatch):
    gui = importlib.import_module("research_harness.gui.app")
    for name in ("OPENALEX_API_KEY", "EPO_CONSUMER_KEY", "EPO_CONSUMER_SECRET"):
        monkeypatch.delenv(name, raising=False)
    observed = []

    def capture(self, spec, runtime, scenario=None):
        observed.append({name: os.environ.get(name) for name in
                         ("OPENALEX_API_KEY", "EPO_CONSUMER_KEY", "EPO_CONSUMER_SECRET")})
        return {"run_id": "test-run"}

    monkeypatch.setattr(gui.InvestigationService, "create_investigation", capture)
    app = gui.create_app(tmp_path, token="unit-token")
    headers = {"x-session-token": "unit-token"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for name, value in (("openalex_api_key", "paper-key"), ("epo_consumer_key", "patent-key"),
                            ("epo_consumer_secret", "patent-secret")):
            assert client.post(f"/api/v1/source-credentials/{name}", json={"api_key": value}, headers=headers).status_code == 200
        assert "paper-key" not in str(client.get("/api/v1/source-credentials").json())
        created = client.post("/api/v1/runs", json={"spec": {}, "runtime": {"mode": "host"}},
                              headers={**headers, "idempotency-key": "source-scoping"})
        assert created.status_code == 200, created.text
        assert observed == [{"OPENALEX_API_KEY": "paper-key", "EPO_CONSUMER_KEY": "patent-key",
                             "EPO_CONSUMER_SECRET": "patent-secret"}]
        assert all(name not in os.environ for name in observed[0])
        assert client.delete("/api/v1/source-credentials/epo_consumer_secret", headers=headers).status_code == 200
        assert client.get("/api/v1/source-credentials").json()["sources"]["epo_consumer_secret"] == "missing"
