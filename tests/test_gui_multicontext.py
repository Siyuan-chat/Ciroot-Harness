import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient

from research_harness.gui.app import create_app
from research_harness.investigation import InvestigationService
from research_harness.rag import RagLibrary


def _make_library(path: Path, text: str, title: str, tmp_path: Path, monkeypatch):
    qdrant=ModuleType("qdrant_client")
    qdrant.models=SimpleNamespace(Filter=lambda **kw:kw,FieldCondition=lambda **kw:kw,MatchAny=lambda **kw:kw)
    bm25=ModuleType("rank_bm25")
    class BM25:
        def __init__(self,corpus): self.corpus=corpus
        def get_scores(self,query):
            words=set(query); return [float(len(words.intersection(document))) for document in self.corpus]
    bm25.BM25Okapi=BM25
    monkeypatch.setitem(sys.modules,"qdrant_client",qdrant)
    monkeypatch.setitem(sys.modules,"rank_bm25",bm25)
    monkeypatch.setattr("research_harness.rag._english_stem",lambda token:token)
    monkeypatch.setattr(RagLibrary,"_version_is_indexed",lambda self,version:bool(self._db.execute("SELECT 1 FROM rag_evidence WHERE version_id=?",(version,)).fetchone()))
    source = tmp_path / f"{title}.txt"
    source.write_text(text, encoding="utf-8")
    catalog = tmp_path / f"{title}.json"
    catalog.write_text(json.dumps({"records": [{"file": source.name, "doi": "10.9/shared-id", "title": title}]}), encoding="utf-8")
    (path / "qdrant").mkdir(parents=True, exist_ok=True)
    class Splitter:
        def __init__(self, **_kwargs): pass
        def split_text(self, value): return [value]
    class Embedder:
        def embed(self, texts, **_kwargs): return iter(type("Vector",(list,),{"tolist":lambda self:list(self)})([1.0]) for _ in texts)
    class Index:
        def collection_exists(self, _name): return True
        def query_points(self, *_args, **_kwargs): return type("Result",(),{"points":[]})()
    monkeypatch.setattr("research_harness.rag.package_version", lambda _name: "gui-fixture")
    monkeypatch.setattr(RagLibrary, "_parse", lambda _self, file: ([{"text": file.read_text(encoding="utf-8"), "locator": {"line_start": 1,"line_end":1}, "section": None, "role": "text"}], None, "full_text", []))
    monkeypatch.setattr(RagLibrary, "_components", lambda _self, **_kwargs: (Embedder(), Index(), Splitter))
    monkeypatch.setattr(RagLibrary, "_index", lambda *_args, **_kwargs: None)
    with RagLibrary(path) as library:
        result = library.import_library(catalog)
        assert result["imported"] == 1
        return result["documents"][0]["document_id"], result["documents"][0]["version_id"]


def test_registered_scopes_isolate_workspace_runs_libraries_collections_and_reference_snapshots(tmp_path, monkeypatch):
    root = tmp_path / "default-workspace"
    workspaces = {"project-a": {"name": "Project A", "path": tmp_path / "workspace-a", "default_library_id": "a-primary"},
                  "project-b": {"name": "Project B", "path": tmp_path / "workspace-b", "default_library_id": "b-primary"}}
    identity_a, version_a = _make_library(tmp_path / "lib-a", "same DOI, version A", "Paper A", tmp_path, monkeypatch)
    identity_b, version_b = _make_library(tmp_path / "lib-b", "same DOI, version B", "Paper B", tmp_path, monkeypatch)
    identity_a2, _ = _make_library(tmp_path / "lib-a2", "separate second library", "Paper A2", tmp_path, monkeypatch)
    identity_b2, _ = _make_library(tmp_path / "lib-b2", "separate fourth library", "Paper B2", tmp_path, monkeypatch)
    assert identity_a == identity_b and version_a != version_b
    collections = lambda doc_id: {"papers": {"name": "Papers", "document_ids": [doc_id]}, "empty": {"name": "Empty group", "document_ids": []}}
    libraries = {
        "a-primary": {"name": "A primary", "path": tmp_path / "lib-a", "workspace_ids": ["project-a"], "default_library_id": True, "collections": collections(identity_a)},
        "a-secondary": {"name": "A secondary", "path": tmp_path / "lib-a2", "workspace_ids": ["project-a"], "collections": collections(identity_a2)},
        "b-primary": {"name": "B primary", "path": tmp_path / "lib-b", "workspace_ids": ["project-b"], "collections": collections(identity_b)},
        "b-secondary": {"name": "B secondary", "path": tmp_path / "lib-b2", "workspace_ids": ["project-b"], "collections": collections(identity_b2)},
    }
    # The default library is selected through workspace.default_library_id.
    app = create_app(root, token="local", registered_workspaces=workspaces, registered_libraries=libraries)
    base = {"x-session-token": "local"}
    scope_a = {"x-workspace-id": "project-a", "x-library-id": "a-primary", "x-collection-id": "papers"}
    scope_b = {"x-workspace-id": "project-b", "x-library-id": "b-primary", "x-collection-id": "papers"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        ctx = client.get("/api/v1/contexts", headers=scope_a).json()
        assert ctx["workspace_id"] == "project-a" and {x["library_id"] for x in ctx["libraries"]} == {"a-primary", "a-secondary"}
        docs_a = client.get("/api/v1/library", headers=scope_a).json()["items"]
        docs_b = client.get("/api/v1/library", headers=scope_b).json()["items"]
        assert docs_a[0]["document_id"] == docs_b[0]["document_id"] == identity_a
        ver_a = client.get(f"/api/v1/library/documents/{identity_a}", headers=scope_a).json()["document"]["versions"]
        ver_b = client.get(f"/api/v1/library/documents/{identity_b}", headers=scope_b).json()["document"]["versions"]
        assert ver_a[0]["version_id"] == version_a and ver_b[0]["version_id"] == version_b
        empty = {**scope_a, "x-collection-id": "empty"}
        assert client.get("/api/v1/library", headers=empty).json()["document_count"] == 0
        assert client.get("/api/v1/library", headers={**scope_a, "x-collection-id": "missing"}).json()["code"] == "RH_GUI_COLLECTION_UNKNOWN"
        assert client.get("/api/v1/library", headers={**scope_a, "x-library-id": "unregistered"}).json()["code"] == "RH_GUI_LIBRARY_UNKNOWN"
        assert client.get("/api/v1/library", headers={**scope_a, "x-workspace-id": "unregistered"}).json()["code"] == "RH_GUI_WORKSPACE_UNKNOWN"
        assert client.get("/api/v1/library", headers={**scope_a, "x-workspace-id": "project-b"}).status_code == 403
        source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
        body = {name: json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec", "runtime", "scenario")}
        run_a = client.post("/api/v1/runs", json=body, headers={**base, **scope_a, "idempotency-key": "same"}).json()["run_id"]
        run_b = client.post("/api/v1/runs", json=body, headers={**base, **scope_b, "idempotency-key": "same"}).json()["run_id"]
        assert run_a != run_b
        assert [x["run_id"] for x in client.get("/api/v1/runs", headers=scope_a).json()["items"]] == [run_a]
        assert [x["run_id"] for x in client.get("/api/v1/runs", headers=scope_b).json()["items"]] == [run_b]
        assert client.get(f"/api/v1/runs/{run_a}", headers=scope_b).status_code == 404
        saved = client.post("/api/v1/model-credentials/openai", json={"api_key":"project-a-only"}, headers={**base, **scope_a})
        assert saved.status_code == 200
        assert client.get("/api/v1/model-credentials", headers=scope_b).json()["providers"]["openai"] == "missing"
        scoped_body={**body,"spec":{**body["spec"],"references":[{"document_id":identity_a,"visibility":"public"}]},"reference_scope":{"library_id":"a-primary","collection_id":"papers"}}
        created = client.post("/api/v1/runs", json=scoped_body, headers={**base, **scope_a, "idempotency-key":"frozen-ref"})
        assert created.status_code == 200, created.text
        frozen_run = created.json()["run_id"]
        before = client.get(f"/api/v1/runs/{frozen_run}/reference-snapshot", headers=scope_a).json()["reference_snapshot"]
        assert before["member_document_versions"] == [{"document_id":identity_a,"current_version_id":version_a,"versions":[version_a]}]
        task=client.get(f"/api/v1/runs/{frozen_run}/tasks",headers=scope_a).json()["items"][0]["payload"]
        assert task["baseline_evidence"][0]["version_id"]==version_a
        assert task["baseline_evidence"][0]["locator"]["line_start"]==1
        assert task["reference_rag_evidence_ids"]==[task["baseline_evidence"][0]["evidence_id"]]
        scoped_body_b={**body,"spec":{**body["spec"],"references":[{"document_id":identity_b,"visibility":"public"}]},"reference_scope":{"library_id":"b-primary","collection_id":"papers"}}
        created_b=client.post("/api/v1/runs",json=scoped_body_b,headers={**base,**scope_b,"idempotency-key":"frozen-ref-b"})
        assert created_b.status_code==200,created_b.text
        task_b=client.get(f"/api/v1/runs/{created_b.json()['run_id']}/tasks",headers=scope_b).json()["items"][0]["payload"]
        assert task_b["baseline_evidence"][0]["document_id"]==identity_b==task["baseline_evidence"][0]["document_id"]
        assert task_b["baseline_evidence"][0]["version_id"]==version_b!=task["baseline_evidence"][0]["version_id"]
        empty_body={**body,"reference_scope":{"library_id":"a-primary","collection_id":"empty"}}
        empty_run=client.post("/api/v1/runs",json=empty_body,headers={**base,**empty,"idempotency-key":"empty-ref"})
        assert empty_run.status_code==200,empty_run.text
        empty_task=client.get(f"/api/v1/runs/{empty_run.json()['run_id']}/tasks",headers=empty).json()["items"][0]["payload"]
        assert empty_task["baseline_evidence"]==[]
        assert empty_task["reference_rag_diagnostics"]["evidence_gap"]
        conflict = client.post("/api/v1/runs", json={**body, "reference_scope":{"library_id":"a-secondary","collection_id":"papers"}}, headers={**base, **{**scope_a,"x-library-id":"a-secondary"}, "idempotency-key":"frozen-ref"})
        assert conflict.status_code == 409
    changed = {**libraries, "a-primary": {**libraries["a-primary"], "collections": collections(identity_a2)}}
    reopened = create_app(root, token="next", registered_workspaces=workspaces, registered_libraries=changed)
    with TestClient(reopened, base_url="http://127.0.0.1") as client:
        after = client.get(f"/api/v1/runs/{frozen_run}/reference-snapshot", headers=scope_a).json()["reference_snapshot"]
        assert after == before
        old_task=client.get(f"/api/v1/runs/{frozen_run}/tasks",headers=scope_a).json()["items"][0]["payload"]
        assert old_task["baseline_evidence"][0]["version_id"]==version_a


def test_active_mutation_returns_typed_busy_while_another_write_is_running(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    entered = threading.Event()
    release = threading.Event()

    def blocked_create(self, *_args, **_kwargs):
        entered.set()
        assert release.wait(5)
        return {"run_id": "hold-run"}

    monkeypatch.setattr(InvestigationService, "create_investigation", blocked_create)
    app = create_app(tmp_path / "workspace", token="secret")
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    body = {name: json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec", "runtime", "scenario")}
    headers = {"x-session-token": "secret", "idempotency-key": "first-write"}

    with TestClient(app, base_url="http://127.0.0.1") as client, ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, "/api/v1/runs", json=body, headers=headers)
        assert entered.wait(3)
        busy = client.post("/api/v1/runs", json=body, headers={**headers, "idempotency-key": "second-write"})
        assert busy.status_code == 409
        assert busy.json()["code"] == "RH_GUI_BUSY"
        assert busy.json()["retryable"] is True
        assert client.get("/api/v1/queue",headers={"x-session-token":"secret"}).json()["items"] == []
        release.set()
        assert first.result(timeout=5).status_code == 200
