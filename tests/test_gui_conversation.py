"""Offline W3 conversation persistence and executor contract tests."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from research_harness.gui.app import create_app
from research_harness.gui.conversation import ConversationStore


def _fixture():
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    return {name: json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8"))
            for name in ("spec", "runtime", "scenario")}


def _wait(client, conversation_id, headers):
    for _ in range(250):
        value = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers).json()["conversation"]
        if value["status"] in {"completed", "partial", "failed", "waiting_credentials", "reply_stopped"}:
            return value
        time.sleep(.02)
    raise AssertionError(value)


def test_conversations_are_workspace_scoped_idempotent_and_scripted_execution_is_explicit(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("W3 offline fixture used network")))
    workspaces = {"one": {"path": tmp_path / "one"}, "two": {"path": tmp_path / "two"}}
    app = create_app(tmp_path / "host", token="t", registered_workspaces=workspaces,
                     registered_libraries={"shared": {"path": tmp_path / "library", "workspace_ids": ["one", "two"]}})
    fixture = _fixture()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        one = {"x-session-token": "t", "x-workspace-id": "one", "x-library-id": "shared"}
        two = {"x-session-token": "t", "x-workspace-id": "two", "x-library-id": "shared"}
        first = client.post("/api/v1/conversations", json={"executor": "scripted", "fixture_id": "synthetic-d19"}, headers={**one, "idempotency-key": "conversation"})
        assert first.status_code == 200, first.text
        conversation_id = first.json()["conversation_id"]
        assert client.post("/api/v1/conversations", json={"executor": "scripted", "fixture_id": "synthetic-d19"}, headers={**one, "idempotency-key": "conversation"}).json()["conversation_id"] == conversation_id
        assert client.get("/api/v1/conversations", headers=two).json()["items"] == []
        clarification = client.post(f"/api/v1/conversations/{conversation_id}/turns", json={"request_id": "turn-1", "content": "请分析膜路线"}, headers=one)
        assert clarification.status_code == 200
        assert clarification.json()["conversation"]["status"] == "ready"
        assert client.get("/api/v1/runs", headers=one).json()["items"] == []
        ready = clarification
        assert any(item["role"] == "assistant" and item["content"].startswith("研究规格") for item in ready.json()["conversation"]["messages"])
        conflict = client.post(f"/api/v1/conversations/{conversation_id}/turns", json={"request_id": "turn-1", "content": "改成真实研究"}, headers=one)
        assert conflict.status_code == 400 and conflict.json()["code"] == "RH_GUI_TURN_CONFLICT"
        assert client.get("/api/v1/runs", headers=one).json()["items"] == []
        executed = client.post(f"/api/v1/conversations/{conversation_id}/execute", json={}, headers={**one, "idempotency-key": "execute-1"})
        assert executed.status_code == 200, executed.text
        result = _wait(client, conversation_id, one)
        assert result["status"] == "completed"
        assert client.get(f"/api/v1/runs/{result['run_id']}/result", headers=one).json()["result"]["synthetic"] is True
        replay = client.post(f"/api/v1/conversations/{conversation_id}/execute", json={}, headers={**one, "idempotency-key": "execute-1"})
        assert replay.json()["replayed"] is True and replay.json()["run_id"] == result["run_id"]
        assert client.post(f"/api/v1/conversations/{conversation_id}/execute", json={}, headers={**one, "idempotency-key": "execute-other"}).status_code == 409
        assert client.get(f"/api/v1/conversations/{conversation_id}", headers=two).status_code == 404
    with TestClient(create_app(tmp_path / "host", token="next", registered_workspaces=workspaces,
                               registered_libraries={"shared": {"path": tmp_path / "library", "workspace_ids": ["one", "two"]}}), base_url="http://127.0.0.1") as client:
        restored = client.get(f"/api/v1/conversations/{conversation_id}", headers={"x-workspace-id": "one", "x-library-id": "shared"}).json()["conversation"]
        assert restored["run_id"] == result["run_id"] and restored["status"] == "completed"


def test_conversation_rejects_scripted_budget_mismatch_and_can_stop_reply(tmp_path):
    fixture = _fixture()
    with TestClient(create_app(tmp_path, token="t"), base_url="http://127.0.0.1") as client:
        headers = {"x-session-token": "t"}
        conversation_id = client.post("/api/v1/conversations", json={"executor": "scripted", "fixture_id": "synthetic-d19"}, headers={**headers, "idempotency-key": "create"}).json()["conversation_id"]
        incompatible_runtime = {**fixture["runtime"], "data_mode": "live", "allow_network": True, "sources": {"openalex": {"anonymous": True}}}
        client.post(f"/api/v1/conversations/{conversation_id}/turns", json={"request_id": "budget", "content": "test", "research_spec": fixture["spec"], "runtime": incompatible_runtime}, headers=headers)
        rejected = client.post(f"/api/v1/conversations/{conversation_id}/execute", json={}, headers={**headers, "idempotency-key": "execute"})
        assert rejected.status_code == 400 and rejected.json()["code"] == "RH_GUI_SCRIPTED_RUNTIME"
        stopped = client.post(f"/api/v1/conversations/{conversation_id}/stop", json={"kind": "reply"}, headers={**headers, "idempotency-key": "stop"})
        assert stopped.status_code == 200 and stopped.json()["conversation"]["status"] == "reply_stopped"


def test_transcripts_use_persisted_insertion_order_for_timestamp_ties(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path)
    scripted = store.create("library", "all", "scripted", "synthetic-d19", "scripted-create", {})
    # Force the old message_id tie-breaker to sort the assistant before the user.
    ids = iter(("turn-first", "z-user", "a-assistant"))
    with monkeypatch.context() as patch:
        patch.setattr("research_harness.gui.conversation.uuid.uuid4", lambda: SimpleNamespace(hex=next(ids)))
        value = store.submit_turn(scripted["conversation_id"], "tie", "question", None, None, reply="answer")
    assert [item["role"] for item in value["messages"]] == ["user", "assistant"]
    assert value["messages"][0]["created_at"] == value["messages"][1]["created_at"]

    external = store.create("library", "all", "external", None, "external-create", {})
    posted = store.submit_external_turn(external["conversation_id"], "external-turn", "handoff question")
    turn_id = posted["messages"][-1]["turn_id"]
    claim = store.claim_external(external["conversation_id"], turn_id, "worker", "claim")
    store.external_progress(external["conversation_id"], turn_id, "worker", claim["claim_id"], "progress", "working", {})
    store.external_reply(external["conversation_id"], turn_id, "worker", claim["claim_id"], "reply", "completed", {})
    # Exercise the tie path with legacy-compatible persisted rows as well.
    store.db.execute("UPDATE conversation_messages SET created=42 WHERE conversation_id=?", (external["conversation_id"],))
    store.db.commit()
    store.close()

    restored = ConversationStore(tmp_path)
    messages = restored.get(external["conversation_id"])["messages"]
    assert [item["role"] for item in messages] == ["user", "progress", "assistant"]
    assert [item["content"] for item in messages] == ["handoff question", "working", "completed"]
    assert all(item["created_at"] == 42 for item in messages)
    scripted_messages = restored.get(scripted["conversation_id"])["messages"]
    assert [item["role"] for item in scripted_messages] == ["user", "assistant"]
    restored.close()
