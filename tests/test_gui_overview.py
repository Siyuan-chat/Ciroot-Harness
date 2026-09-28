import json
from pathlib import Path
import requests

from fastapi.testclient import TestClient

from research_harness.gui import app as gui_app
from research_harness.gui.app import create_app
from research_harness.investigation import InvestigationService


def _fixtures():
    source = Path(__file__).parents[1] / "src/research_harness/examples/investigation"
    return {name: json.loads((source / f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec", "runtime", "scenario")}


def test_overview_is_scoped_bounded_and_preserves_unknown_counts(tmp_path):
    app = create_app(tmp_path, token="overview-token")
    headers = {"x-session-token": "overview-token", "x-workspace-id": "default", "x-library-id": "default", "x-collection-id": "all"}
    fixture = _fixtures()
    with InvestigationService(tmp_path) as service:
        for i in range(6):
            spec = {**fixture["spec"], "project_id": f"project-{i}"}
            service.create_investigation(spec, fixture["runtime"], fixture["scenario"])
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/v1/overview", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["workspace"] == {"workspace_id": "default", "name": "Default workspace"}
        assert len(data["recent_runs"]) == 5
        assert data["recent_runs"][0]["synthetic"] is True
        assert data["recent_runs"][0]["outcome"] == "waiting"
        assert data["library"]["document_count"] is None
        assert data["review_summary"]["open_run_issue_count"] is None
        assert data["golden_demo"]["available"] is True
        assert client.get("/api/v1/overview", headers={**headers, "x-workspace-id": "unregistered"}).status_code == 404


def test_overview_reports_golden_demo_unavailable_when_packaged_inputs_are_missing(tmp_path, monkeypatch):
    app = create_app(tmp_path, token="overview-token")
    monkeypatch.setattr(gui_app, "_golden_demo_available", lambda: False)
    headers = {"x-session-token": "overview-token", "x-workspace-id": "default", "x-library-id": "default", "x-collection-id": "all"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/v1/overview", headers=headers)
    assert response.status_code == 200
    assert response.json()["golden_demo"] == {"available": False}


def test_overview_tolerates_legacy_result_and_report_failures(tmp_path, monkeypatch):
    app = create_app(tmp_path, token="overview-token")
    fixture = _fixtures()
    with InvestigationService(tmp_path) as service:
        run_id = service.create_investigation(fixture["spec"], fixture["runtime"], fixture["scenario"])["run_id"]
    original_result = InvestigationService.get_result
    original_report = InvestigationService.build_report_data

    def old_result(self, ident):
        if ident == run_id:
            raise RuntimeError("legacy result unavailable")
        return original_result(self, ident)

    def old_report(self, ident):
        if ident == run_id:
            raise RuntimeError("legacy report unavailable")
        return original_report(self, ident)

    monkeypatch.setattr(InvestigationService, "get_result", old_result)
    monkeypatch.setattr(InvestigationService, "build_report_data", old_report)
    headers = {"x-workspace-id": "default", "x-library-id": "default", "x-collection-id": "all"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/v1/overview", headers=headers)
    assert response.status_code == 200
    run = response.json()["recent_runs"][0]
    assert run["run_id"] == run_id
    assert run["verified_claim_count"] is None
    assert run["open_issue_count"] is None
    assert response.json()["review_summary"]["open_run_issue_count"] is None


def test_scoped_golden_adapter_is_idempotent_and_preserves_legacy_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(requests.sessions.Session, "request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network call")))
    app = create_app(tmp_path, token="overview-token")
    headers = {"x-session-token": "overview-token", "x-workspace-id": "default",
               "x-library-id": "default", "x-collection-id": "all", "idempotency-key": "same-run"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        missing_auth = client.post("/api/v1/demos/golden", json={}, headers={"idempotency-key": "no-auth"})
        assert missing_auth.status_code == 403
        missing_key = client.post("/api/v1/demos/golden", json={}, headers={key: value for key, value in headers.items() if key != "idempotency-key"})
        assert missing_key.status_code == 400
        assert missing_key.json()["code"] == "RH_GUI_HTTP"
        assert missing_key.json()["message"] == "idempotency_key required"
        first = client.post("/api/v1/demos/golden", json={}, headers=headers)
        replay = client.post("/api/v1/demos/golden", json={}, headers=headers)
        assert first.status_code == replay.status_code == 200
        created = first.json()
        assert created["outcome"] == "partial"
        assert created["synthetic"] is True
        assert created["candidate_count"] == 3
        assert created["evidence_document_count"] == 2
        assert created["verified_claim_count"] == 2
        assert created["open_issue_count"] == 1
        run_id = created["run_id"]
        assert replay.json()["run_id"] == run_id
        assert client.get("/api/v1/runs/" + run_id, headers=headers).json()["run_id"] == run_id
        result_response = client.get("/api/v1/runs/" + run_id + "/result", headers=headers)
        report_response = client.get("/api/v1/runs/" + run_id + "/report-data", headers=headers)
        assert result_response.status_code == report_response.status_code == 200
        result = result_response.json()["result"]
        report = report_response.json()["report_data"]
        assert result["outcome"] == "partial" and result["synthetic"] is True
        assert len(result["evidence"]) >= 1
        assert len(report["claims"]) == created["verified_claim_count"]
        assert report["sections"] and all(section["claim_ids"] for section in report["sections"])
        assert all(claim["evidence_refs"] for claim in report["claims"])
        assert client.post("/api/v1/demos/golden", json={"workspace": "elsewhere"}, headers=headers).status_code == 400
        legacy = client.get("/api/v1/golden-demo")
        assert legacy.status_code == 200 and legacy.json()["schema_version"] == "1"
