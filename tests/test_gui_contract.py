import base64

import pytest
import json
import hashlib
from pathlib import Path
from fastapi.testclient import TestClient

from research_harness.gui.app import _page
from research_harness.gui.app import create_app
from research_harness.investigation import InvestigationService
from research_harness.rag import RagLibrary
from research_harness.investigation_review import ReviewStore


def test_page_cursor_and_validation():
    first = _page([1, 2, 3], 2, None)
    assert first["items"] == [1, 2]
    assert _page([1, 2, 3], 2, first["next_cursor"])["items"] == [3]
    with pytest.raises(ValueError):
        _page([1], 0, None)
    with pytest.raises(ValueError):
        _page([1], 2, "not-a-cursor")


def test_local_api_security_and_synthetic_run(tmp_path):
    app = create_app(tmp_path, token="unit-token")
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    body = {name: json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec", "runtime", "scenario")}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/runs", headers={"host":"evil.example"}).status_code == 403
        assert client.get("/api/v1/runs", headers={"origin":"https://evil.example"}).status_code == 403
        assert client.post("/api/v1/runs", json=body).status_code == 403
        assert client.post("/api/v1/runs", json=body, headers={"x-session-token":"wrong","idempotency-key":"wrong"}).status_code == 403
        unindexed = client.get("/api/v1/library").json()
        assert unindexed["index_status"] == "not_indexed"
        assert unindexed["document_count"] is None
        headers = {"x-session-token":"unit-token", "idempotency-key":"create-1"}
        created = client.post("/api/v1/runs", json=body, headers=headers)
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
        assert client.get(f"/api/v1/runs/{run_id}").json()["synthetic"] is True
        assert client.post("/api/v1/runs", json=body, headers=headers).json()["run_id"] == run_id
        conflicting = {**body, "spec":{**body["spec"],"research_question":"Different"}}
        assert client.post("/api/v1/runs", json=conflicting, headers=headers).status_code == 409
        assert len(client.get("/api/v1/runs").json()["items"]) == 1
        assert client.get("/api/v1/runs").json()["items"][0]["data_mode"] == "synthetic"
        assert client.get(f"/api/v1/runs/{run_id}/tasks").json()["items"][0]["role"] == "planning"
        pending_report = client.get(f"/api/v1/runs/{run_id}/report-data")
        assert pending_report.status_code == 400
        assert pending_report.json()["code"] == "RH_REPORT_DATA"
        pending_export = client.post(f"/api/v1/runs/{run_id}/export", json={}, headers={**headers,"idempotency-key":"export-pending"})
        assert pending_export.status_code == 400
        assert pending_export.json()["code"] == "RH_REPORT_DATA"
        stopped = client.post(f"/api/v1/runs/{run_id}/stop", json={}, headers={**headers,"idempotency-key":"stop-1"})
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["status"] == "stopped"
        assert client.post(f"/api/v1/runs/{run_id}/advance", json={}, headers={**headers,"idempotency-key":"advance-stopped"}).json()["outcome"] == "stopped"
        tasks_before = client.get(f"/api/v1/runs/{run_id}/tasks").json()["items"]
        resumed = client.post(f"/api/v1/runs/{run_id}/resume", json={}, headers={**headers,"idempotency-key":"resume-1"})
        assert resumed.status_code == 200, resumed.text
        assert client.get(f"/api/v1/runs/{run_id}").json()["budget"] == stopped.json()["budget"]
        assert client.get(f"/api/v1/runs/{run_id}/tasks").json()["items"] == tasks_before

    reopened = create_app(tmp_path, token="new-token")
    with TestClient(reopened, base_url="http://127.0.0.1") as client:
        current = client.get(f"/api/v1/runs/{run_id}").json()
        assert current["synthetic"] is True
        assert current["budget"] == stopped.json()["budget"]
        assert client.get(f"/api/v1/runs/{run_id}/tasks").json()["items"] == tasks_before
        assert client.post("/api/v1/runs", json=body, headers={"x-session-token":"new-token","idempotency-key":"create-1"}).json()["run_id"] == run_id
        assert client.get("/api/v1/artifacts/does-not-exist").status_code == 404


def test_artifact_path_escape_is_rejected(tmp_path):
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    spec = json.loads((source / "synthetic-spec.json").read_text(encoding="utf-8"))
    runtime = json.loads((source / "synthetic-runtime.json").read_text(encoding="utf-8"))
    scenario = json.loads((source / "synthetic-scenario.json").read_text(encoding="utf-8"))
    with InvestigationService(tmp_path) as svc:
        run_id = svc.create_investigation(spec,runtime,scenario)["run_id"]
        path = "../outside.txt"
        svc.db.execute("UPDATE investigations SET result=? WHERE id=?", (json.dumps({"artifacts":[{"path":path}]}), run_id))
        svc.db.commit()
    (tmp_path.parent / "outside.txt").write_text("secret", encoding="utf-8")
    artifact_id = hashlib.sha256((run_id+":"+path).encode()).hexdigest()
    with TestClient(create_app(tmp_path, token="t"), base_url="http://127.0.0.1") as client:
        listed = client.get(f"/api/v1/runs/{run_id}/artifacts").json()["items"]
        assert listed[0]["name"] == "outside.txt"
        assert listed[0]["path"] is None
        assert client.get(f"/api/v1/artifacts/{artifact_id}").status_code == 404


def test_library_version_file_and_discovery_document_projection(tmp_path):
    with RagLibrary(tmp_path) as rag:
        rag._db.execute("INSERT INTO rag_documents VALUES (?,?,?,?,?,?,?,?,?,?)", ("doc-1","Title",None,2026,"paper",str(tmp_path / "private.pdf"),"v1","completed","partial","[]"))
        rag._db.execute("INSERT INTO rag_versions(version_id,document_id,content_sha256,parser,page_count,coverage,errors,source_path,created) VALUES (?,?,?,?,?,?,?,?,?)", ("v1","doc-1","sha","test",2,"partial","[]",str(tmp_path / "private.pdf"),0))
        rag._db.commit()
    (tmp_path / "qdrant").mkdir(exist_ok=True)
    (tmp_path / "raw").mkdir(exist_ok=True)
    (tmp_path / "raw" / "v1.pdf").write_bytes(b"%PDF-1.4\n")
    with InvestigationService(tmp_path) as svc:
        source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
        spec = json.loads((source / "synthetic-spec.json").read_text(encoding="utf-8"))
        runtime = json.loads((source / "synthetic-runtime.json").read_text(encoding="utf-8"))
        scenario = json.loads((source / "synthetic-scenario.json").read_text(encoding="utf-8"))
        run_id = svc.create_investigation(spec,runtime,scenario)["run_id"]
        svc.db.execute("INSERT INTO discovery_documents VALUES (?,?,?)", (run_id,"pub-1",json.dumps({"publication_id":"pub-1","text":"<claim id='1'>A</claim>","epo_sections":[{"section":"claims","locator":{"kind":"claim","value":"1"},"text":"A"}],"source_xml":[{"raw_xml_path":"C:/private.xml"}]})))
        svc.db.execute("INSERT INTO discovery_documents VALUES (?,?,?)", (run_id,"paper-1",json.dumps({"document_id":"paper-1","content_type":"application/pdf","base64_bytes":base64.b64encode(b"%PDF-1.4\n").decode()})))
        svc.db.commit()
    with TestClient(create_app(tmp_path, token="t"), base_url="http://127.0.0.1") as client:
        document = client.get("/api/v1/library/documents/doc-1").json()["document"]
        assert "source_path" not in document
        assert "source_path" not in document["versions"][0]
        assert client.get(document["versions"][0]["file_url"]).status_code == 200
        assert client.get("/api/v1/library/documents/doc-1/versions/other/file").status_code == 404
        publication = client.get(f"/api/v1/runs/{run_id}/documents/pub-1").json()["document"]
        assert publication["epo_sections"][0]["locator"]["value"] == "1"
        assert "source_xml" not in publication
        paper = client.get(f"/api/v1/runs/{run_id}/documents/paper-1").json()["document"]
        assert "base64_bytes" not in paper
        assert client.get(paper["file_url"]).content == b"%PDF-1.4\n"


def test_frozen_report_evidence_without_rag_index(tmp_path):
    evidence_id = "ev-1a8a36084e573139922b5fe5"
    evidence = {"evidence_id":evidence_id,"document_id":"doc-919616a2d08e7c6784331bd4","version_id":"ver-9ae4903902f5401f21d8707e","text":"16. 청구항 1 내지 청구항 15 중 어느 한 항의 이온전도성 고분자를 포함하는 음이온 교환막.","locator":{"kind":"xml_node","value":"/world-patent-data[1]/fulltext-documents[1]/fulltext-document[1]/claims[1]/claim[1]"}}
    with InvestigationService(tmp_path) as svc:
        svc.db.execute("INSERT INTO investigations VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("inv-frozen","{}","{}","{}","partial","completed","{}",0,0,"{}","[]"))
        svc.db.execute("INSERT INTO frozen_reports VALUES (?,?,?)", ("inv-frozen",json.dumps({"evidence":[evidence],"bibliography":[{"id":evidence["document_id"],"title":"POLYMÈRE CONDUCTEUR D'IONS","publication_id":"WO2026182370A1","type":"patent"}]}),0))
        svc.db.commit()
    with TestClient(create_app(tmp_path, token="t"), base_url="http://127.0.0.1") as client:
        response = client.get(f"/api/v1/evidence/{evidence_id}")
        assert response.status_code == 200, response.text
        item = response.json()["evidence"]
        assert item["document_id"] == evidence["document_id"]
        assert item["locator"] == evidence["locator"]
        assert response.json()["locator_insufficient"] is False
        document = client.get(f"/api/v1/runs/inv-frozen/documents/{evidence['document_id']}")
        assert document.status_code == 200, document.text
        publication = document.json()["document"]
        assert publication["publication_id"] == "WO2026182370A1"
        assert publication["content_scope"] == "frozen_evidence_excerpts"
        assert publication["epo_sections"][0]["locator"] == evidence["locator"]


def _synthetic_answer(task):
    role, payload = task["role"], task["payload"]
    if role == "planning":
        return {"search_plan":{"queries":[{"query_id":"paper-query","source":"synthetic-paper","query":"synthetic crosslinking membrane","input_refs":[],"parent_query_id":None},{"query_id":"patent-query","source":"synthetic-patent","query":"synthetic crosslinked polymer","input_refs":[],"parent_query_id":None}]}}
    if role in ("paper_search","patent_search"):
        return {"candidates":[{"document_id":item["document_id"],"relevance":"relevant","reason":"matches synthetic plan"} for item in payload["candidates"]]}
    if role == "evidence_analysis":
        return {"findings":[{"finding_id":"f0","finding":"Synthetic evidence was extracted.","evidence_ids":[payload["evidence"][0]["evidence_id"]],"value":None,"unit":None,"conditions":None}]}
    if role == "business_judgment":
        return {"judgments":[{"document_id":item["document_id"],"relevance":"relevant","human_review_required":False,"reason":"synthetic scope"} for item in payload["documents"]]}
    if role == "synthesis":
        evidence = payload["evidence"][0]
        return {"claims":[{"claim_id":"c0","claim":evidence["text"],"finding_refs":[0],"evidence_refs":[evidence["evidence_id"]],"quote":evidence["text"],"document_id":evidence["document_id"],"version_id":evidence["version_id"]}]}
    if role == "writing":
        return {"sections":[{"deliverable_type":kind,"language":"en","section_id":kind,"title":"Synthetic result","body":"The supplied synthetic evidence supports the route.","claim_ids":["c0"]} for kind in ("technical_report","literature_review")]}
    return {"verification":{"status":"supported","conclusion":"Supported by normalized synthetic evidence.","supported_claim_refs":[0]}}


def test_http_synthetic_flow_export_restart_without_network(tmp_path, monkeypatch):
    import requests
    def no_network(*args, **kwargs):
        raise AssertionError("synthetic GUI flow attempted external HTTP")
    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    source = Path(__file__).parents[1] / "examples/investigation"
    body = {name:json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec","runtime","scenario")}
    headers = {"x-session-token":"t"}
    with TestClient(create_app(tmp_path,token="t"),base_url="http://127.0.0.1") as client:
        created = client.post("/api/v1/runs",json=body,headers={**headers,"idempotency-key":"create"})
        assert created.status_code == 200, created.text
        run_id = created.json()["run_id"]
        for step in range(20):
            state = client.get(f"/api/v1/runs/{run_id}").json()
            if state["status"] in {"completed","partial","failed"}:
                break
            tasks = client.get(f"/api/v1/runs/{run_id}/tasks").json()["items"]
            for task in tasks:
                response = client.post(f"/api/v1/runs/{run_id}/tasks/{task['task_id']}",json={"task_version":task["task_version"],"result":_synthetic_answer(task)},headers={**headers,"idempotency-key":f"task-{task['task_id']}"})
                assert response.status_code == 200, response.text
            advanced = client.post(f"/api/v1/runs/{run_id}/advance",json={},headers={**headers,"idempotency-key":f"advance-{step}"})
            assert advanced.status_code == 200, advanced.text
        assert state["status"] == "partial" and state["stage"] == "completed", state
        result = client.get(f"/api/v1/runs/{run_id}/result").json()["result"]
        assert result["synthetic"] is True
        assert {issue["code"] for issue in result["issues"]} >= {"RH_SECTION_DRAFT", "RH_SECTION_TITLE_DRAFT"}
        report = client.get(f"/api/v1/runs/{run_id}/report-data").json()["report_data"]
        assert {item["deliverable_type"] for item in report["sections"]} == {"technical_report","literature_review"}
        export = client.post(f"/api/v1/runs/{run_id}/export",json={},headers={**headers,"idempotency-key":"export"})
        assert export.status_code == 200, export.text
        artifacts = export.json()["artifacts"]
        assert len(artifacts) >= 5
        assert all(item["name"] for item in artifacts)
        assert client.get(f"/api/v1/artifacts/{artifacts[0]['artifact_id']}").status_code == 200
    with TestClient(create_app(tmp_path,token="new"),base_url="http://127.0.0.1") as client:
        restored = client.get(f"/api/v1/runs/{run_id}").json()
        assert restored["status"] == "partial" and restored["stage"] == "completed"
        assert client.get(f"/api/v1/runs/{run_id}/report-data").json()["report_data"]["synthetic"] is True
        assert client.get(f"/api/v1/runs/{run_id}/artifacts").json()["items"]


def test_monitor_review_http_persists_history_and_rejects_plain_run_issue(tmp_path):
    store = ReviewStore(tmp_path)
    original = store.record_judgment("monitor-1","company-1","doc-1","v1","rule-1",{"relevance":"uncertain","human_review_required":True,"reason":"model uncertainty"},["ev-1"])
    issue_id = original["issue_id"]
    store.close()
    headers = {"x-session-token":"t","idempotency-key":"decide-1"}
    body = {"decision":"relevant","note":"checked original"}
    with TestClient(create_app(tmp_path,token="t"),base_url="http://127.0.0.1") as client:
        listed = client.get("/api/v1/reviews?monitor_id=monitor-1").json()["items"]
        assert len(listed) == 1
        assert listed[0]["effective_judgment"]["relevance"] == "uncertain"
        assert listed[0]["events"][0]["kind"] == "model"
        first = client.post(f"/api/v1/reviews/{issue_id}/decision",json=body,headers=headers)
        assert first.status_code == 200, first.text
        assert client.post(f"/api/v1/reviews/{issue_id}/decision",json=body,headers=headers).json() == first.json()
        assert client.post("/api/v1/reviews/inv-ordinary-issue/decision",json=body,headers={**headers,"idempotency-key":"wrong-scope"}).status_code == 404
    with TestClient(create_app(tmp_path,token="new"),base_url="http://127.0.0.1") as client:
        row = client.get("/api/v1/reviews?monitor_id=monitor-1").json()["items"][0]
        assert row["human_decision"] == "relevant"
        assert row["effective_judgment"]["relevance"] == "relevant"
        assert [item["kind"] for item in row["events"]].count("human") == 1
        assert [item["kind"] for item in row["events"]].count("model") == 1


def test_observation_cursor_survives_restart_and_detects_gap(tmp_path):
    source = Path(__file__).parents[1] / "examples/investigation"
    body = {name:json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec","runtime","scenario")}
    headers = {"x-session-token":"t","idempotency-key":"create"}
    with TestClient(create_app(tmp_path,token="t"),base_url="http://127.0.0.1") as client:
        run_id = client.post("/api/v1/runs",json=body,headers=headers).json()["run_id"]
        first = client.get(f"/api/v1/runs/{run_id}/events?after=0").json()
        assert first["transport"] == "poll"
        assert len(first["events"]) == 1
        seq = first["next_seq"]
        assert first["events"][0]["payload"]["status"] == "waiting_model"
        client.post(f"/api/v1/runs/{run_id}/stop",json={},headers={**headers,"idempotency-key":"stop"})
        later = client.get(f"/api/v1/runs/{run_id}/events?after={seq}").json()
        assert len(later["events"]) == 1
        assert later["events"][0]["seq"] > seq
        assert later["events"][0]["payload"]["status"] == "stopped"
        seq2 = later["next_seq"]
    with TestClient(create_app(tmp_path,token="new"),base_url="http://127.0.0.1") as client:
        assert client.get(f"/api/v1/runs/{run_id}/events?after={seq}").json()["events"][0]["seq"] == seq2
        assert client.get(f"/api/v1/runs/{run_id}/events?after={seq2+99}").status_code == 409


def test_registered_xml_original_and_locator(tmp_path):
    source = Path(__file__).parents[1] / "examples/investigation"
    spec = json.loads((source / "synthetic-spec.json").read_text(encoding="utf-8"))
    runtime = json.loads((source / "synthetic-runtime.json").read_text(encoding="utf-8"))
    scenario = json.loads((source / "synthetic-scenario.json").read_text(encoding="utf-8"))
    with InvestigationService(tmp_path) as svc:
        run_id = svc.create_investigation(spec,runtime,scenario)["run_id"]
        relative = f"epo/{run_id}/claims.xml"
        target = tmp_path / relative
        target.parent.mkdir(parents=True)
        content = b"<claims><claim id='16'>Claim text</claim></claims>"
        target.write_bytes(content)
        doc = {"document_id":"pub","publication_id":"WO123A1","source_xml":[{"section":"claims","raw_xml_path":relative,"sha256":hashlib.sha256(content).hexdigest()}],"epo_sections":[{"section":"claims","locator":{"kind":"claim","value":"16"},"text":"Claim text"}]}
        svc.db.execute("INSERT INTO discovery_documents VALUES (?,?,?)",(run_id,"pub",json.dumps(doc)))
        svc.db.commit()
    with TestClient(create_app(tmp_path,token="t"),base_url="http://127.0.0.1") as client:
        public = client.get(f"/api/v1/runs/{run_id}/documents/pub").json()["document"]
        assert "source_xml" not in public
        url = public["originals"][0]["url"]
        assert client.get(url).content == content
        assert client.get(f"/api/v1/runs/{run_id}/documents/pub/locate?kind=claim&value=16").json()["text"] == "Claim text"
        assert client.get(f"/api/v1/runs/{run_id}/documents/pub/locate?kind=claim&value=99").status_code == 404
        assert client.get(url.replace(public["originals"][0]["original_id"],"unregistered")).status_code == 404


def test_frozen_bibliography_maps_registered_patent_and_pdf_by_identity(tmp_path):
    source = Path(__file__).parents[1] / "examples/investigation"
    spec = json.loads((source / "synthetic-spec.json").read_text(encoding="utf-8"))
    runtime = json.loads((source / "synthetic-runtime.json").read_text(encoding="utf-8"))
    scenario = json.loads((source / "synthetic-scenario.json").read_text(encoding="utf-8"))
    with InvestigationService(tmp_path) as svc:
        run_id = svc.create_investigation(spec,runtime,scenario)["run_id"]
        xml = b"<claims><claim id='16'>Text</claim></claims>"
        relative = f"epo/{run_id}/claims.xml"
        target = tmp_path / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(xml)
        patent = {"publication_id":"WO2026182370A1","source_xml":[{"section":"claims","raw_xml_path":relative,"sha256":hashlib.sha256(xml).hexdigest()}],"epo_sections":[{"section":"claims","locator":{"kind":"claim","value":"16"},"text":"Text"}]}
        paper = {"document_id":"https://openalex.org/W2100100522","doi":"10.1039/c4ee01303d","content_type":"application/pdf","base64_bytes":base64.b64encode(b"%PDF-1.4\n").decode()}
        for key,payload in (("WO2026182370A1",patent),("https://openalex.org/W2100100522",paper)):
            svc.db.execute("INSERT INTO discovery_documents VALUES (?,?,?)",(run_id,key,json.dumps(payload)))
        report = {"bibliography":[{"id":"doc-919616a2d08e7c6784331bd4","publication_id":"WO2026182370A1"},{"id":"doc-a36059a433ed2af5e9ad4a5f","doi":"10.1039/c4ee01303d"}],"evidence":[]}
        svc.db.execute("INSERT INTO frozen_reports VALUES (?,?,?)",(run_id,json.dumps(report),0))
        svc.db.commit()
    with TestClient(create_app(tmp_path,token="t"),base_url="http://127.0.0.1") as client:
        patent_doc = client.get(f"/api/v1/runs/{run_id}/documents/doc-919616a2d08e7c6784331bd4").json()["document"]
        assert patent_doc["canonical_document_id"] == "doc-919616a2d08e7c6784331bd4"
        assert client.get(patent_doc["originals"][0]["url"]).content == xml
        paper_doc = client.get(f"/api/v1/runs/{run_id}/documents/doc-a36059a433ed2af5e9ad4a5f").json()["document"]
        assert paper_doc["canonical_document_id"] == "doc-a36059a433ed2af5e9ad4a5f"
        assert client.get(paper_doc["file_url"] + "#page=1").content == b"%PDF-1.4\n"
