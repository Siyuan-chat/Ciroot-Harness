"""Offline contract tests for the W2 managed GUI control channel."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from research_harness.gui.app import create_app
from research_harness.gui.control import ControlClient, remove_descriptor, write_descriptor
import research_harness.gui.control_mcp as control_mcp


def _run_payload() -> dict:
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    return {name: json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8"))
            for name in ("spec", "runtime", "scenario")}


def _control(action: str, payload: dict, *, key: str | None = None, scope: dict | None = None) -> dict:
    value = {"action": action, "actor": "offline-cli", "request_id": "req-1", "payload": payload,
             "scope": scope or {"workspace_id": "default", "library_id": "default", "collection_id": "all"}}
    if key: value["idempotency_key"] = key
    return value


def test_control_writes_same_gui_run_and_enforces_scope_and_replay(tmp_path):
    app = create_app(tmp_path, token="control-token")
    headers = {"x-session-token": "control-token"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        created = client.post("/api/v1/control", json=_control("run.create", _run_payload(), key="run-create"), headers=headers)
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
        # The standard GUI route reads exactly the run created by managed control.
        assert client.get(f"/api/v1/runs/{run_id}").json()["run_id"] == run_id
        replay = client.post("/api/v1/control", json=_control("run.create", _run_payload(), key="run-create"), headers=headers)
        assert replay.json()["run_id"] == run_id
        advance = client.post("/api/v1/control", json=_control("run.advance", {"run_id": run_id}, key="advance-1"), headers=headers)
        assert advance.status_code == 200
        assert advance.json().get("command_id") or advance.json().get("run_id") == run_id
        assert client.post("/api/v1/control", json=_control("run.status", {"run_id": run_id}, scope={"workspace_id": "other"}), headers=headers).status_code == 403
        unopened = client.post("/api/v1/control", json=_control("view.open", {"client_id": "not-connected", "run_id": run_id, "page": "report"}), headers=headers)
        assert unopened.status_code == 200 and unopened.json()["navigated"] is False
        subscribed = client.post("/api/v1/control", json=_control("view.subscribe", {"client_id": "ui-1"}), headers=headers)
        assert subscribed.json()["connected"] is True
        queued = client.post("/api/v1/control", json=_control("view.open", {"client_id": "ui-1", "run_id": run_id, "page": "report"}), headers=headers)
        assert queued.json()["queued"] is True and queued.json()["navigated"] is False
        events = client.get("/api/v1/control/clients/ui-1/events", headers=headers)
        assert events.status_code == 200 and events.json()["events"][0]["target"]["run_id"] == run_id
        assert client.get("/api/v1/control/clients/ui-1/events").status_code == 403


def test_descriptor_unavailable_service_and_mcp_forwarding_are_offline(tmp_path, monkeypatch):
    descriptor = write_descriptor(tmp_path, "http://127.0.0.1:9", "never-in-argv")
    stored = json.loads(descriptor.read_text(encoding="utf-8"))
    assert "never-in-argv" not in descriptor.read_text(encoding="utf-8")
    assert stored["token_reference"] == "session.token"
    assert ControlClient(descriptor).call("workspace.list", {"actor": "test", "request_id": "r", "scope": {}})["code"] == "RH_GUI_CONTROL_UNAVAILABLE"

    calls = []
    class FakeClient:
        def __init__(self, _descriptor): pass
        def call(self, action, payload):
            calls.append((action, payload)); return {"schema_version": "1", "result": "forwarded"}
    monkeypatch.setattr(control_mcp, "ControlClient", FakeClient)
    bridge = control_mcp.ManagedControlMCP(str(descriptor))
    assert bridge.call("run.advance", {"scope": {}, "run_id": "inv-000000000001"})["result"] == "forwarded"
    assert calls == [("run.advance", {"scope": {}, "run_id": "inv-000000000001"})]
    remove_descriptor(tmp_path)
    assert not descriptor.exists()


def test_descriptor_rejects_non_loopback_and_proxy_bypass(tmp_path, monkeypatch):
    import pytest
    for url in ("https://127.0.0.1:9", "http://example.test:9", "http://127.0.0.1", "http://127.0.0.1:9/path"):
        with pytest.raises(ValueError): write_descriptor(tmp_path, url, "token")
    descriptor = write_descriptor(tmp_path, "http://localhost:9", "token")
    monkeypatch.setenv("http_proxy", "http://example.test:8080")
    assert ControlClient(descriptor).call("workspace.list", {"scope": {}})["code"] == "RH_GUI_CONTROL_UNAVAILABLE"
