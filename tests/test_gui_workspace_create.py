from pathlib import Path

from fastapi.testclient import TestClient

import research_harness.gui.app as gui


def _headers(key="workspace-create"):
    return {"x-session-token": "local-token", "idempotency-key": key}


def test_create_empty_workspaces_are_distinct_idempotent_and_unindexed(tmp_path):
    app = gui.create_app(tmp_path, token="local-token")
    body = {"name": "  Same display name  ", "description": "local draft", "reference_library_ids": []}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        first = client.post("/api/v1/workspaces", json=body, headers=_headers()).json()
        replay = client.post("/api/v1/workspaces", json=body, headers=_headers()).json()
        second = client.post("/api/v1/workspaces", json={**body, "description": "second"}, headers=_headers("workspace-create-2")).json()
        assert first == replay
        assert first["workspace_id"] != second["workspace_id"]
        assert first["name"] == "Same display name"
        assert first["libraries"] == [{"library_id": first["default_library_id"], "name": "Same display name library", "read_only": False, "index_status": "unindexed"}]
        assert client.get("/api/v1/library", headers={"x-workspace-id": first["workspace_id"]}).json()["index_status"] == "not_indexed"
        assert client.post("/api/v1/workspaces", json={**body, "description": "changed"}, headers=_headers()).status_code == 409
        assert client.post("/api/v1/workspaces", json={"name": "path", "path": str(tmp_path)}, headers=_headers("path")).status_code == 400
        listed = client.get("/api/v1/workspaces").json()["items"]
        assert {item["workspace_id"] for item in listed} >= {"default", first["workspace_id"], second["workspace_id"]}
    assert (tmp_path / "gui-workspaces" / first["workspace_id"]).is_dir()
    assert (tmp_path / "gui-libraries" / first["default_library_id"]).is_dir()


def test_create_workspace_reference_library_is_read_only_and_survives_restart(tmp_path):
    old_library = tmp_path / "trusted-library"
    old_library.mkdir()
    app = gui.create_app(tmp_path / "data", token="local-token", registered_libraries={
        "old-library": {"name": "Trusted", "path": old_library, "workspace_ids": ["default"]}
    })
    with TestClient(app, base_url="http://127.0.0.1") as client:
        created = client.post("/api/v1/workspaces", json={"name": "Review", "reference_library_ids": ["old-library"]}, headers=_headers()).json()
        assert created["default_library_id"] == "old-library"
        assert created["libraries"][0]["read_only"] is True
        assert created["libraries"][0]["index_status"] == "unindexed"
        assert old_library.exists() and list(old_library.iterdir()) == []
        workspace_id = created["workspace_id"]
    restarted = gui.create_app(tmp_path / "data", token="next-token", registered_libraries={
        "old-library": {"name": "Trusted", "path": old_library, "workspace_ids": ["default"]}
    })
    with TestClient(restarted, base_url="http://127.0.0.1") as client:
        registry = client.get("/api/v1/registry").json()
        restored = next(item for item in registry["workspaces"] if item["workspace_id"] == workspace_id)
        assert restored["default_library_id"] == "old-library"
        assert restored["libraries"][0]["read_only"] is True
        assert client.get("/api/v1/library", headers={"x-workspace-id": workspace_id, "x-library-id": "old-library"}).status_code == 200


def test_failed_registry_persist_removes_new_directories_and_registration(tmp_path, monkeypatch):
    app = gui.create_app(tmp_path, token="local-token")
    monkeypatch.setattr(gui.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("disk failure")))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post("/api/v1/workspaces", json={"name": "Will fail"}, headers=_headers())
        assert response.status_code == 400
        assert client.get("/api/v1/workspaces").json()["items"] == [{"workspace_id": "default", "name": "Default workspace", "description": ""}]
    assert not list((tmp_path / "gui-workspaces").glob("ws-*"))
    assert not list((tmp_path / "gui-libraries").glob("lib-*"))
