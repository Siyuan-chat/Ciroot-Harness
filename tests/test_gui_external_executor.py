"""Offline W4 external-executor delivery contract, including a local MCP bridge."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient

from research_harness.gui.app import create_app
from research_harness.gui.control import write_descriptor
from research_harness.gui.control_mcp import ManagedControlMCP


def _api_config():
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    runtime = json.loads((source / "synthetic-runtime.json").read_text(encoding="utf-8"))
    runtime.update(mode="api", allow_network=True, model_api={"provider": "openai", "model": "unit-model", "api_key_env": "OPENAI_API_KEY", "max_output_tokens": 120, "timeout_seconds": 5})
    runtime["budget"]["max_model_calls"] = 3
    return {"provider": "openai", "model": "unit-model", "max_planning_calls": 2, "max_output_tokens": 120,
            "timeout_seconds": 5, "total_model_calls": 3, "runtime_template": runtime}


def _post(url, body, token="w4-token", extra=None):
    headers = {"content-type": "application/json", "x-session-token": token, **(extra or {})}
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _bridge_payload(request_id, payload, *, actor="synthetic-external", key=None):
    value = {"actor": actor, "request_id": request_id,
             "scope": {"workspace_id": "default", "library_id": "default", "collection_id": "all"},
             "payload": payload}
    if key:
        value["idempotency_key"] = key
    return value


def test_external_turn_uses_real_local_mcp_bridge_and_persists_across_restart(tmp_path):
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    app = create_app(tmp_path, token="w4-token")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True); thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            status, _ = _post(base + "/api/v1/conversations", {"executor": "external"}, extra={"idempotency-key": "create"})
            if status == 200: break
        except urllib.error.URLError:
            time.sleep(.02)
    else:
        raise AssertionError("local GUI service did not start")
    # First request created the external conversation; retry gives its stable identity.
    _, created = _post(base + "/api/v1/conversations", {"executor": "external"}, extra={"idempotency-key": "create"})
    conversation_id = created["conversation_id"]
    status, turn = _post(base + f"/api/v1/conversations/{conversation_id}/turns", {"request_id": "user-1", "content": "仅使用受控动作检查合成任务"})
    assert status == 200 and turn["conversation"]["status"] == "waiting_external"

    bridge = ManagedControlMCP(str(write_descriptor(tmp_path, base, "w4-token")))
    pending = bridge.call("conversation.list_pending", _bridge_payload("pending-1", {}))
    item = pending["items"][0]
    assert item["conversation_id"] == conversation_id and item["content"] == "仅使用受控动作检查合成任务"
    # Exercise the actual MCP 2.x STDIO server, not only its in-process adapter.
    async def stdio_probe():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        source_path = str(Path(__file__).parents[1] / "src")
        params = StdioServerParameters(command=sys.executable,
                                       args=["-m", "research_harness.gui.control_mcp", "--descriptor", str(tmp_path / "control" / "instance.json")],
                                       env={**os.environ, "PYTHONPATH": source_path + os.pathsep + os.environ.get("PYTHONPATH", "")})
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                assert {tool.name for tool in (await session.list_tools()).tools} == {"control"}
                common = {"actor": "stdio-external", "request_id": "stdio-1", "scope": {"workspace_id": "default", "library_id": "default", "collection_id": "all"}}
                listed = await session.call_tool("control", {"action": "workspace.list", "payload": common})
                assert listed.is_error is False and "default" in listed.content[0].text
                pending_result = await session.call_tool("control", {"action": "conversation.list_pending", "payload": {**common, "request_id": "stdio-2", "payload": {}}})
                assert pending_result.is_error is False and conversation_id in pending_result.content[0].text
    asyncio.run(stdio_probe())
    claim = bridge.call("conversation.claim", _bridge_payload("claim-1", {"conversation_id": conversation_id, "turn_id": item["turn_id"], "lease_seconds": 5}))
    claim_id = claim["claim_id"]
    held = bridge.call("conversation.claim", _bridge_payload("claim-other", {"conversation_id": conversation_id, "turn_id": item["turn_id"]}, actor="other"))
    assert held["code"] == "RH_GUI_EXTERNAL_LEASE_HELD"
    context = bridge.call("conversation.context", _bridge_payload("context-1", {"conversation_id": conversation_id, "turn_id": item["turn_id"], "claim_id": claim_id}))
    assert context["conversation"]["messages"][0]["content"] == "仅使用受控动作检查合成任务"

    # This is a W2 managed tool call through the same bridge and GUI service.
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    run_payload = {name: json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec", "runtime", "scenario")}
    run = bridge.call("run.create", _bridge_payload("run-1", run_payload, key="run-create"))
    progress_payload = {"conversation_id": conversation_id, "turn_id": item["turn_id"], "claim_id": claim_id, "content": "已创建受控任务。", "object_refs": {"run_id": run["run_id"]}}
    progress = bridge.call("conversation.progress", _bridge_payload("progress-1", progress_payload))
    assert bridge.call("conversation.progress", _bridge_payload("progress-1", progress_payload))["message_id"] == progress["message_id"]
    reply_payload = {"conversation_id": conversation_id, "turn_id": item["turn_id"], "claim_id": claim_id, "content": "任务已创建，尚未声称运行完成。", "object_refs": {"run_id": run["run_id"]}}
    reply = bridge.call("conversation.reply", _bridge_payload("reply-1", reply_payload))
    assert bridge.call("conversation.reply", _bridge_payload("reply-1", reply_payload))["message_id"] == reply["message_id"]
    assert bridge.call("conversation.reply", _bridge_payload("reply-1", {**reply_payload, "content": "different"}))["code"] == "RH_GUI_EXTERNAL_CONFLICT"
    ack = bridge.call("conversation.ack", _bridge_payload("ack-1", {"conversation_id": conversation_id, "turn_id": item["turn_id"], "claim_id": claim_id}))
    assert ack["state"] == "acked"
    server.should_exit = True; thread.join(timeout=5)
    assert not thread.is_alive()

    # A new GUI process keeps both the transcript and the completed delivery state.
    with TestClient(create_app(tmp_path, token="next"), base_url="http://127.0.0.1") as client:
        restored = client.get(f"/api/v1/conversations/{conversation_id}").json()["conversation"]
        assert restored["status"] == "awaiting_input"
        assert any(message["content"] == "任务已创建，尚未声称运行完成。" for message in restored["messages"])


def test_external_scope_and_expired_lease_are_not_replayed(tmp_path, monkeypatch):
    app = create_app(tmp_path, token="t")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        headers = {"x-session-token": "t"}
        conversation_id = client.post("/api/v1/conversations", json={"executor": "external"}, headers={**headers, "idempotency-key": "new"}).json()["conversation_id"]
        client.post(f"/api/v1/conversations/{conversation_id}/turns", json={"request_id": "u", "content": "wait"}, headers=headers)
        pending = client.post("/api/v1/control", json={"action": "conversation.list_pending", **_bridge_payload("p", {})}, headers=headers).json()["items"][0]
        claimed = client.post("/api/v1/control", json={"action": "conversation.claim", **_bridge_payload("c", {"conversation_id": conversation_id, "turn_id": pending["turn_id"], "lease_seconds": 5})}, headers=headers).json()
        denied = client.post("/api/v1/control", json={"action": "conversation.claim", **_bridge_payload("wrong", {"conversation_id": conversation_id, "turn_id": pending["turn_id"]}), "scope": {"workspace_id": "other"}}, headers=headers)
        assert denied.status_code == 403
        # Advance only the persistence module's clock: expiry permits redelivery, not a duplicate reply/tool result.
        import research_harness.gui.conversation as conversation_module
        monkeypatch.setattr(conversation_module.time, "time", lambda: claimed["lease_until"] + 1)
        renewed = client.post("/api/v1/control", json={"action": "conversation.claim", **_bridge_payload("reclaim", {"conversation_id": conversation_id, "turn_id": pending["turn_id"]}, actor="replacement")}, headers=headers)
        assert renewed.status_code == 200 and renewed.json()["claim_id"] != claimed["claim_id"]


def test_executor_switch_preserves_conversation_and_rejects_pending_or_busy_work(tmp_path):
    with TestClient(create_app(tmp_path, token="t"), base_url="http://127.0.0.1") as client:
        headers = {"x-session-token": "t"}
        conversation_id = client.post("/api/v1/conversations", json={"executor": "external"}, headers={**headers, "idempotency-key": "new"}).json()["conversation_id"]
        client.post(f"/api/v1/conversations/{conversation_id}/turns", json={"request_id": "user", "content": "preserve this context"}, headers=headers)
        pending_switch = client.post(f"/api/v1/conversations/{conversation_id}/executor", json={"executor": "api", "api_config": _api_config()}, headers={**headers, "idempotency-key": "switch-pending"})
        assert pending_switch.status_code == 409 and pending_switch.json()["code"] == "RH_GUI_EXECUTOR_SWITCH_EXTERNAL_PENDING"
        pending = client.post("/api/v1/control", json={"action": "conversation.list_pending", **_bridge_payload("list", {})}, headers=headers).json()["items"][0]
        claim = client.post("/api/v1/control", json={"action": "conversation.claim", **_bridge_payload("claim", {"conversation_id": conversation_id, "turn_id": pending["turn_id"]})}, headers=headers).json()
        reply = {"conversation_id": conversation_id, "turn_id": pending["turn_id"], "claim_id": claim["claim_id"], "content": "handoff complete", "object_refs": {}}
        assert client.post("/api/v1/control", json={"action": "conversation.reply", **_bridge_payload("reply", reply)}, headers=headers).status_code == 200
        assert client.post("/api/v1/control", json={"action": "conversation.ack", **_bridge_payload("ack", {"conversation_id": conversation_id, "turn_id": pending["turn_id"], "claim_id": claim["claim_id"]})}, headers=headers).status_code == 200
        switched = client.post(f"/api/v1/conversations/{conversation_id}/executor", json={"executor": "api", "api_config": _api_config()}, headers={**headers, "idempotency-key": "switch"})
        assert switched.status_code == 200 and switched.json()["conversation"]["conversation_id"] == conversation_id and switched.json()["conversation"]["executor"] == "api"
        replay = client.post(f"/api/v1/conversations/{conversation_id}/executor", json={"executor": "api", "api_config": _api_config()}, headers={**headers, "idempotency-key": "switch"})
        assert replay.json()["conversation"] == switched.json()["conversation"]
        conflict = client.post(f"/api/v1/conversations/{conversation_id}/executor", json={"executor": "external"}, headers={**headers, "idempotency-key": "switch"})
        assert conflict.status_code == 409 and conflict.json()["code"] == "RH_GUI_IDEMPOTENCY_CONFLICT"
        restored = client.get(f"/api/v1/conversations/{conversation_id}").json()["conversation"]
        assert [message["content"] for message in restored["messages"]] == ["preserve this context", "handoff complete"]
        with sqlite3.connect(tmp_path / "gui-conversations.sqlite") as db:
            db.execute("UPDATE conversations SET status='queued' WHERE conversation_id=?", (conversation_id,))
        busy = client.post(f"/api/v1/conversations/{conversation_id}/executor", json={"executor": "external"}, headers={**headers, "idempotency-key": "switch-busy"})
        assert busy.status_code == 409 and busy.json()["code"] == "RH_GUI_EXECUTOR_SWITCH_BUSY"
