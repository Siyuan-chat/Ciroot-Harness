import json

import requests
from fastapi.testclient import TestClient

from research_harness.gui.app import create_app
from research_harness.investigation import InvestigationService


def _headers(key=None):
    headers = {"x-session-token": "demo-token"}
    if key:
        headers["idempotency-key"] = key
    return headers


def test_gui_golden_demo_runs_replays_and_reopens_offline(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Golden Demo attempted network access")

    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "MOONSHOT_API_KEY",
                 "OPENALEX_API_KEY", "EPO_CONSUMER_KEY", "EPO_CONSUMER_SECRET"):
        monkeypatch.delenv(name, raising=False)
    original_report_data = InvestigationService.build_report_data

    def with_xpath(self, run_id):
        value = original_report_data(self, run_id)
        value["evidence"][0]["locator"]["xpath"] = "/html/body/p[1]"
        return value

    monkeypatch.setattr(InvestigationService, "build_report_data", with_xpath)
    app = create_app(tmp_path, token="demo-token")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        empty = client.get("/api/v1/golden-demo")
        assert empty.status_code == 200 and empty.json() == {"schema_version": "1", "demo": None}
        denied = client.post("/api/v1/golden-demo", json={}, headers={"idempotency-key": "denied"})
        assert denied.status_code == 403
        override = client.post("/api/v1/golden-demo", json={"workspace": str(tmp_path / "private")}, headers=_headers("override"))
        assert override.status_code == 400
        created = client.post("/api/v1/golden-demo", json={}, headers=_headers("run-1"))
        assert created.status_code == 200, created.text
        payload = created.json()
        demo = payload["demo"]
        run_id = demo["run_id"]
        assert payload["schema_version"] == "1"
        assert demo["workspace_label"] == "Golden Demo"
        assert demo["status"]["status"] == "partial"
        assert demo["result"]["outcome"] == "partial"
        assert any(issue.get("code") == "RH_NORMALIZE_XML" and issue.get("status") == "open" for issue in demo["result"]["issues"])
        assert demo["spec"]["research_question"] == "Compare synthetic membrane routes."
        assert demo["report_data"]["evidence"][0]["locator"]["xpath"] == "/html/body/p[1]"
        assert all("path" not in key.lower() for key in demo["result"])
        report_evidence = {item["evidence_id"]: item for item in demo["report_data"]["evidence"]}
        claims = [claim for claim in demo["report_data"]["claims"] if claim.get("verification") == "verified"]
        assert len(claims) >= 2
        for claim in claims:
            evidence = report_evidence[claim["evidence_refs"][0]]
            assert claim["document_id"] == evidence["document_id"]
            assert claim["version_id"] == evidence["version_id"]
            assert claim["quote"] in evidence["text"]
            assert evidence["locator"]
        reports = {(report["type"], report["language"]): report["content"] for report in demo["reports"]}
        assert {("technical_report", "en"), ("literature_review", "en")} <= set(reports)
        for report_type in ("technical_report", "literature_review"):
            body = reports[(report_type, "en")]
            assert "SYNTHETIC REPORT" in body
            assert any(claim["claim"] in body and claim["quote"] in body for claim in claims)
            assert any(evidence_id in body and evidence["document_id"] in body and evidence["version_id"] in body
                       for evidence_id, evidence in report_evidence.items() if evidence["document_id"] != "paper-review-gap")
        serialized = json.dumps(payload, ensure_ascii=False)
        assert str(tmp_path) not in serialized
        replay = client.post("/api/v1/golden-demo", json={}, headers=_headers("run-1"))
        assert replay.status_code == 200 and replay.json()["demo"]["run_id"] == run_id
        second = client.post("/api/v1/golden-demo", json={}, headers=_headers("run-2"))
        assert second.status_code == 200 and second.json()["demo"]["run_id"] != run_id
        second_id = second.json()["demo"]["run_id"]

    reopened_app = create_app(tmp_path, token="demo-token")
    with TestClient(reopened_app, base_url="http://127.0.0.1") as client:
        recovered = client.get("/api/v1/golden-demo")
        assert recovered.status_code == 200
        assert recovered.json()["demo"]["run_id"] == second_id
        previous = client.get(f"/api/v1/golden-demo/runs/{run_id}")
        assert previous.status_code == 200 and previous.json()["demo"]["run_id"] == run_id
        invalid = client.get("/api/v1/golden-demo/runs/inv-000000000000")
        assert invalid.status_code == 404
        assert str(tmp_path) not in invalid.text
    with InvestigationService(tmp_path / "public-golden-demo") as service:
        run_ids = [row["id"] for row in service.db.execute("SELECT id FROM investigations")]
        assert len(run_ids) == 2


def test_gui_golden_demo_rejects_missing_or_outside_report_artifact(tmp_path):
    app = create_app(tmp_path, token="demo-token")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        created = client.post("/api/v1/golden-demo", json={}, headers=_headers("run"))
        assert created.status_code == 200, created.text
        run_id = created.json()["demo"]["run_id"]
    with InvestigationService(tmp_path / "public-golden-demo") as service:
        row = service._run(run_id)
        result = json.loads(row["result"])
        markdown = next(item for item in result["artifacts"] if item.get("format") == "markdown" and item["type"] == "technical_report")
        report_path = (service.root / markdown["path"]).resolve()
        report_path.unlink()
    app = create_app(tmp_path, token="demo-token")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        missing = client.get("/api/v1/golden-demo")
        assert missing.status_code == 400
        assert missing.json()["code"] == "RH_GOLDEN_DEMO_REPORT_ARTIFACT"
    with InvestigationService(tmp_path / "public-golden-demo") as service:
        row = service._run(run_id)
        result = json.loads(row["result"])
        markdown = next(item for item in result["artifacts"] if item.get("format") == "markdown" and item["type"] == "technical_report")
        markdown["path"] = "../../outside.md"
        service.db.execute("UPDATE investigations SET result=? WHERE id=?", (json.dumps(result), run_id))
        service.db.commit()
    app = create_app(tmp_path, token="demo-token")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        outside = client.get("/api/v1/golden-demo")
        assert outside.status_code == 400
        assert outside.json()["code"] == "RH_GOLDEN_DEMO_REPORT_ARTIFACT"
        assert str(tmp_path) not in outside.text


def test_gui_golden_demo_empty_and_malformed_saved_state(tmp_path):
    app = create_app(tmp_path, token="demo-token")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/golden-demo").json()["demo"] is None
    pointer = tmp_path / "public-golden-demo" / "gui-golden-demo-latest.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text("not-json", encoding="utf-8")
    app = create_app(tmp_path, token="demo-token")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/v1/golden-demo")
        assert response.status_code == 400
        assert response.json()["code"] == "RH_GOLDEN_DEMO_STATE"
        missing = client.get("/api/v1/golden-demo/runs/inv-000000000000")
        assert missing.status_code == 404 and "not found" in missing.json()["message"]
