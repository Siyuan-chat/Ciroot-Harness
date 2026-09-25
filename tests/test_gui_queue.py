import json
import hashlib
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from research_harness.gui.app import create_app
from research_harness.investigation import InvestigationService


def _body(mode="host"):
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    result = {name: json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8"))
              for name in ("spec", "runtime", "scenario")}
    if mode == "api":
        result["runtime"]["mode"] = "api"
        result["runtime"]["allow_network"] = True
        result["runtime"]["model_api"] = {"provider": "openai", "model": "test-model", "api_key_env": "OPENAI_API_KEY",
                                           "max_output_tokens": 100, "timeout_seconds": 1}
        result["runtime"]["budget"]["max_model_calls"] = 1
    return result


def _wait(client, wid, command_id, status, headers, timeout=5):
    deadline = time.time() + timeout
    scoped = {**headers, "x-workspace-id": wid}
    while time.time() < deadline:
        result = client.get(f"/api/v1/queue/{command_id}", headers=scoped).json()
        if result.get("status") == status:
            return result
        time.sleep(.02)
    raise AssertionError(f"command {command_id} did not reach {status}: {result}")


def test_persistent_queue_scopes_cancel_restart_credentials_external_lock_stop_and_ui(tmp_path, monkeypatch):
    root = tmp_path / "default"
    workspaces = {"a": {"path": tmp_path / "a", "default_library_id": "shared"},
                  "b": {"path": tmp_path / "b", "default_library_id": "shared"}}
    app = create_app(root, token="secret", registered_workspaces=workspaces,
                     registered_libraries={"shared": {"path": tmp_path / "lib", "workspace_ids": ["a", "b"]}},
                     static_dir=Path(__file__).parents[1] / "frontend")
    entered, release = threading.Event(), threading.Event()
    hold_next = {"enabled": False}
    called = []
    original = InvestigationService.advance_investigation

    def blocked(self, run_id):
        called.append(str(self.root))
        if hold_next["enabled"]:
            hold_next["enabled"] = False
            entered.set()
            assert release.wait(5)
            return {"run_id": run_id, "stage": "queued-fixture", "status": "waiting"}
        return original(self, run_id)

    monkeypatch.setattr(InvestigationService, "advance_investigation", blocked)
    headers = {"x-session-token": "secret"}
    scope_a = {**headers, "x-workspace-id": "a"}
    scope_b = {**headers, "x-workspace-id": "b"}
    with TestClient(app, base_url="http://127.0.0.1") as client, ThreadPoolExecutor(max_workers=1) as pool:
        run_a = client.post("/api/v1/runs", json=_body(), headers={**scope_a, "idempotency-key": "create-a"}).json()["run_id"]
        run_b = client.post("/api/v1/runs", json=_body(), headers={**scope_b, "idempotency-key": "create-b"}).json()["run_id"]
        hold_next["enabled"] = True
        first = pool.submit(client.post, f"/api/v1/runs/{run_a}/advance", json={}, headers={**scope_a, "idempotency-key": "advance-a"})
        assert entered.wait(5)
        active_state=client.get("/api/v1/queue",headers=scope_a).json()
        first_command=active_state["active_command_id"]
        assert first_command and active_state["current_object"]==run_a
        queued = client.post(f"/api/v1/runs/{run_b}/advance", json={}, headers={**scope_b, "idempotency-key": "advance-b"})
        assert queued.status_code == 200 and queued.json().get("status") == "queued", queued.text
        command_id = queued.json()["command_id"]
        assert client.get("/api/v1/queue", headers=scope_a).json()["items"][0]["run_id"] == run_a
        assert client.get("/api/v1/queue", headers=scope_b).json()["items"][0]["workspace_id"] == "b"
        assert client.get(f"/api/v1/queue/{queued.json()['command_id']}",headers=scope_a).status_code==404
        cancelled = client.post(f"/api/v1/queue/{command_id}/cancel", json={}, headers=scope_b)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        retry = client.post(f"/api/v1/runs/{run_b}/advance", json={}, headers={**scope_b, "idempotency-key": "advance-b"})
        assert retry.json()["command_id"] == command_id and retry.json()["status"] == "cancelled"
        exported=client.post(f"/api/v1/runs/{run_b}/export",json={"languages":["zh"]},headers={**scope_b,"idempotency-key":"export-b"})
        duplicate=client.post(f"/api/v1/runs/{run_b}/export",json={"languages":["zh"]},headers={**scope_b,"idempotency-key":"export-b"})
        conflict=client.post(f"/api/v1/runs/{run_b}/export",json={"languages":["en"]},headers={**scope_b,"idempotency-key":"export-b"})
        assert exported.json()["command_id"]==duplicate.json()["command_id"] and conflict.status_code==409
        assert client.post(f"/api/v1/queue/{exported.json()['command_id']}/cancel",json={},headers=scope_b).json()["status"]=="cancelled"
        release.set()
        first_result=first.result(timeout=5)
        assert first_result.status_code == 200, first_result.text
        time.sleep(.1)
        assert len(called) == 1

        # An external MCP-style workspace lock is represented as a waiting queue item.
        lock_entered,lock_release=threading.Event(),threading.Event()
        def hold_external():
            with InvestigationService(workspaces["b"]["path"]):
                lock_entered.set(); assert lock_release.wait(5)
        lock_thread=threading.Thread(target=hold_external); lock_thread.start(); assert lock_entered.wait(3)
        external = client.post(f"/api/v1/runs/{run_b}/advance", json={}, headers={**scope_b, "idempotency-key": "external-lock"})
        assert external.status_code == 200 and external.json()["status"] == "waiting_external_lock"
        assert client.get(f"/api/v1/queue/{external.json()['command_id']}", headers=scope_b).json()["status"] == "waiting_external_lock"
        lock_release.set(); lock_thread.join(3)
        client.post("/api/v1/queue/resume", json={}, headers=scope_b)
        _wait(client, "b", external.json()["command_id"], "completed", headers)

        changed_entered,changed_release=threading.Event(),threading.Event()
        def hold_and_change():
            with InvestigationService(workspaces["b"]["path"]) as service:
                changed_entered.set(); assert changed_release.wait(5)
                service.db.execute("UPDATE investigations SET stage='changed-under-external-lock' WHERE id=?",(run_b,)); service.db.commit()
        changed_thread=threading.Thread(target=hold_and_change); changed_thread.start(); assert changed_entered.wait(3)
        changed=client.post(f"/api/v1/runs/{run_b}/advance",json={},headers={**scope_b,"idempotency-key":"external-version-change"})
        assert changed.status_code==200 and changed.json()["status"]=="waiting_external_lock"
        changed_release.set(); changed_thread.join(3)
        refused=client.post("/api/v1/queue/resume",json={},headers=scope_b)
        assert refused.status_code==200
        _wait(client,"b",changed.json()["command_id"],"needs_review",headers)
        assert client.get(f"/api/v1/queue/{changed.json()['command_id']}",headers=scope_b).json()["error_code"]=="RH_GUI_PRECONDITION_CHANGED"

        # Missing API credentials are workspace local and are never copied into queue storage.
        monkeypatch.setenv("OPENAI_API_KEY", "synthetic-placeholder")
        created_api = client.post("/api/v1/runs", json=_body("api"), headers={**scope_b, "idempotency-key": "create-api"})
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert created_api.status_code == 200, created_api.text
        run_api = created_api.json()["run_id"]
        missing = client.post(f"/api/v1/runs/{run_api}/model-step", json={}, headers={**scope_b, "idempotency-key": "model-no-key"})
        assert missing.status_code == 200, missing.text
        _wait(client,"b",missing.json()["command_id"],"waiting_credentials",headers)
        queue_file = root / "gui-command-queue.sqlite"
        db = sqlite3.connect(queue_file)
        serialized = " ".join(str(row) for row in db.execute("SELECT params,error_message FROM commands"))
        assert "OPENAI_API_KEY" not in serialized and "secret" not in serialized
        db.close()

        # Stop is accepted while a command holds the writer, and takes precedence next.
        entered.clear(); release.clear()
        hold_next["enabled"] = True
        second = pool.submit(client.post, f"/api/v1/runs/{run_a}/advance", json={}, headers={**scope_a, "idempotency-key": "advance-a2"})
        assert entered.wait(5)
        stopped = client.post(f"/api/v1/runs/{run_a}/stop", json={}, headers={**scope_a, "idempotency-key": "stop-a"})
        assert stopped.status_code == 200 and stopped.json()["accepted"] is True
        release.set(); assert second.result(timeout=5).status_code == 200
        _wait(client, "a", stopped.json()["command_id"], "completed", headers)
        assert client.get("/", headers=scope_a).status_code == 200
        script = client.get("/app.js", headers=scope_a)
        assert script.status_code == 200 and "持久命令队列" in script.text

    # A command found in running state after restart becomes needs_review and is not replayed.
    now = time.time()
    db = sqlite3.connect(root / "gui-command-queue.sqlite")
    interrupted_id="a"*32; persisted_id="b"*32
    db.execute("INSERT INTO commands(command_id,workspace_id,library_id,collection_id,run_id,operation,params,idempotency_key,digest,status,created,updated,error_code,error_message,eligible,manual_reviewed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)",
               (interrupted_id, "a", "shared", "all", run_a, "advance", "{}", "interrupted-key", "digest-a", "running", now, now, None, None))
    db.execute("INSERT INTO commands(command_id,workspace_id,library_id,collection_id,run_id,operation,params,idempotency_key,digest,status,created,updated,error_code,error_message,eligible,manual_reviewed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)",
               (persisted_id, "a", "shared", "all", run_a, "advance", "{}", "persisted-key", "digest-b", "queued", now+1, now+1, None, None))
    db.commit(); db.close()
    restarted = create_app(root, token="new-secret", registered_workspaces=workspaces,
                           registered_libraries={"shared": {"path": tmp_path / "lib", "workspace_ids": ["a", "b"]}},
                           static_dir=Path(__file__).parents[1] / "frontend")
    with TestClient(restarted, base_url="http://127.0.0.1") as client:
        state = client.get("/api/v1/queue", headers={"x-session-token":"new-secret","x-workspace-id": "a"}).json()
        interrupted = next(item for item in state["items"] if item["command_id"] == interrupted_id)
        assert interrupted["status"] == "needs_review"
        persisted = next(item for item in state["items"] if item["command_id"] == persisted_id)
        assert persisted["status"] == "queued" and persisted["requires_resume"] is True
        rejected=client.post("/api/v1/queue/resume",json={"reviewed_command_ids":[interrupted_id]},headers={"x-session-token":"new-secret","x-workspace-id":"a"})
        assert rejected.status_code == 400
        resumed=client.post("/api/v1/queue/resume",json={"reviewed_command_ids":[interrupted_id],"confirm_needs_review":True},headers={"x-session-token":"new-secret","x-workspace-id":"a"})
        assert resumed.status_code == 409 and resumed.json()["code"]=="RH_GUI_PRECONDITION_CHANGED"
        reviewed=client.get(f"/api/v1/queue/{interrupted_id}",headers={"x-session-token":"new-secret","x-workspace-id":"a"}).json()
        assert reviewed["status"] == "needs_review"


def test_persistent_queue_enforces_global_limit_of_100(tmp_path):
    app=create_app(tmp_path / "workspace",token="secret")
    queue_file=tmp_path / "workspace" / "gui-command-queue.sqlite"
    now=time.time(); db=sqlite3.connect(queue_file)
    db.executemany("INSERT INTO commands(command_id,workspace_id,library_id,collection_id,run_id,operation,params,idempotency_key,digest,status,created,updated,error_code,error_message,eligible,manual_reviewed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)",[
        (f"{index:032x}","default","default","all","inv-000000000001","advance","{}",f"limit-{index}",f"digest-{index}","queued",now+index,now,None,None)
        for index in range(100)])
    db.commit(); db.close()
    with TestClient(app,base_url="http://127.0.0.1") as client:
        response=client.post("/api/v1/runs/inv-000000000001/advance",json={},headers={"x-session-token":"secret","idempotency-key":"over-cap"})
        assert response.status_code==429 and response.json()["code"]=="RH_GUI_QUEUE_FULL"
        assert client.get("/api/v1/queue",headers={"x-session-token":"secret"}).json()["queued_count"]==100



def test_queue_reads_require_token_and_recovery_requires_unchanged_core_state(tmp_path):
    root=tmp_path/"workspace"
    app=create_app(root,token="secret")
    source=Path(__file__).parents[1]/"src/research_harness/examples/investigation"
    body={name:json.loads((source/f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec","runtime","scenario")}
    with TestClient(app,base_url="http://127.0.0.1") as client:
        run=client.post("/api/v1/runs",json=body,headers={"x-session-token":"secret","idempotency-key":"create"}).json()["run_id"]
        with InvestigationService(root) as service:
            core=service.db.execute("SELECT id,status,stage,budget,result FROM investigations WHERE id=?",(run,)).fetchone()
            tasks=service.db.execute("SELECT id,task_version,role,task_type,status,result_hash FROM model_tasks WHERE run_id=? ORDER BY id",(run,)).fetchall()
            calls=service.db.execute("SELECT id,task_id,task_version,status,usage FROM model_api_calls WHERE run_id=? ORDER BY id",(run,)).fetchall()
            pre=json.dumps({"run_id":core["id"],"status":core["status"],"stage":core["stage"],"budget_hash":hashlib.sha256((core["budget"] or "").encode()).hexdigest(),"result_hash":hashlib.sha256((core["result"] or "").encode()).hexdigest(),"tasks":[list(x) for x in tasks],"calls":[[x["id"],x["task_id"],x["task_version"],x["status"],hashlib.sha256((x["usage"] or "").encode()).hexdigest()] for x in calls]},sort_keys=True,separators=(",",":"))
        cid="c"*32; now=time.time(); digest=hashlib.sha256(json.dumps({"workspace_id":"default","library_id":"default","collection_id":"all","body":{"run_id":run}},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        qdb=sqlite3.connect(root/"gui-command-queue.sqlite")
        qdb.execute("INSERT INTO commands(command_id,workspace_id,library_id,collection_id,run_id,operation,params,idempotency_key,digest,status,created,updated,error_code,error_message,eligible,manual_reviewed,request_digest,precondition_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,?,?)",(cid,"default","default","all",run,"advance","{}",hashlib.sha256(b"recover").hexdigest(),"digest","running",now,now,None,None,digest,pre))
        qdb.commit(); qdb.close()
        assert client.get("/api/v1/queue").status_code==403
        assert client.get(f"/api/v1/queue/{cid}").status_code==403
        db=sqlite3.connect(root/"gui-command-queue.sqlite")
        db.execute("UPDATE commands SET status='running' WHERE command_id=?",(cid,)); db.commit(); db.close()
    restarted=create_app(root,token="new-secret")
    with TestClient(restarted,base_url="http://127.0.0.1") as client:
        headers={"x-session-token":"new-secret"}
        state=client.get("/api/v1/queue",headers=headers).json()
        assert next(x for x in state["items"] if x["command_id"]==cid)["status"]=="needs_review"
        with InvestigationService(root) as service:
            service.db.execute("UPDATE investigations SET stage='changed-after-crash' WHERE id=?",(run,)); service.db.commit()
        response=client.post("/api/v1/queue/resume",json={"reviewed_command_ids":[cid],"confirm_needs_review":True},headers=headers)
        assert response.status_code==409 and response.json()["code"]=="RH_GUI_PRECONDITION_CHANGED"
        state=client.get(f"/api/v1/queue/{cid}",headers=headers).json()
        assert state["status"]=="needs_review"


def test_concurrent_queue_idempotency_dispatches_once_and_conflicts_on_body(tmp_path,monkeypatch):
    app=create_app(tmp_path/"workspace",token="secret")
    source=Path(__file__).parents[1]/"src/research_harness/examples/investigation"
    body={name:json.loads((source/f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec","runtime","scenario")}
    called=[]
    def count(self,run_id,*args,**kwargs):
        called.append(run_id)
        return {"artifacts":[]}
    monkeypatch.setattr(InvestigationService,"export_report",count)
    with TestClient(app,base_url="http://127.0.0.1") as client, ThreadPoolExecutor(max_workers=4) as pool:
        headers={"x-session-token":"secret","idempotency-key":"same"}
        run=client.post("/api/v1/runs",json=body,headers={**headers,"idempotency-key":"create"}).json()["run_id"]
        def send(): return client.post(f"/api/v1/runs/{run}/export",json={"languages":["zh"]},headers=headers)
        responses=list(pool.map(lambda _:send(),range(4)))
        assert all(x.status_code==200 for x in responses)
        assert all(x.json().get("artifacts")==[] for x in responses)
        qdb=sqlite3.connect(tmp_path/"workspace"/"gui-command-queue.sqlite")
        ids={row[0] for row in qdb.execute("SELECT command_id FROM queue_replays WHERE workspace_id='default'")}; qdb.close()
        assert len(ids)==1
        conflict=client.post(f"/api/v1/runs/{run}/export",json={"languages":["en"]},headers=headers)
        assert conflict.status_code==409
        _wait(client,"default",next(iter(ids)),"completed",headers)
        again=send()
        assert again.status_code==200 and again.json().get("artifacts")==[]
        assert len(called)==1
