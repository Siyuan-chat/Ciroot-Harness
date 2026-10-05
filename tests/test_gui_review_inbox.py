import json

from fastapi.testclient import TestClient

from research_harness.gui.app import create_app
from research_harness.investigation import InvestigationService


def _fixtures():
    from pathlib import Path
    source=Path(__file__).parents[1]/"src/research_harness/examples/investigation"
    return {name:json.loads((source/f"synthetic-{name}.json").read_text(encoding="utf-8")) for name in ("spec","runtime","scenario")}


def test_review_inbox_is_bounded_scoped_read_only_and_never_actionable(tmp_path,monkeypatch):
    app=create_app(tmp_path,token="review-token")
    fixture=_fixtures()
    with InvestigationService(tmp_path) as service:
        run_ids=[service.create_investigation({**fixture["spec"],"project_id":f"review-{index}"},fixture["runtime"],fixture["scenario"])["run_id"] for index in range(3)]
    newest=run_ids[-1]
    middle=run_ids[-2]
    oldest=run_ids[0]
    results={
        newest:{"outcome":"partial","synthetic":True,"issues":[{"code":"RH_NORMALIZE_XML","status":"open","message":"XML normalization was incomplete"},{"code":"RH_SOURCE_PARTIAL"}]},
        oldest:{"outcome":"completed","synthetic":False,"issues":[]},
    }
    original=InvestigationService.get_result
    def result(self,run_id):
        if run_id==middle:raise RuntimeError("legacy result unavailable")
        if run_id in results:return results[run_id]
        return original(self,run_id)
    def forbidden_review_list(self,*args,**kwargs):
        raise AssertionError("monitor reviews must not be enumerated globally")
    monkeypatch.setattr(InvestigationService,"get_result",result)
    monkeypatch.setattr(InvestigationService,"review_list",forbidden_review_list)
    headers={"x-session-token":"review-token","x-workspace-id":"default","x-library-id":"default","x-collection-id":"all"}
    with TestClient(app,base_url="http://127.0.0.1") as client:
        response=client.get("/api/v1/review-inbox?limit=2",headers=headers)
        assert response.status_code==200
        data=response.json()
        assert data["context"]=={"workspace_id":"default","library_id":"default","collection_id":"all"}
        assert data["workspace_id"]=="default"
        assert data["monitor_reviews_included"] is False
        assert data["next_cursor"] is not None
        assert len(data["items"])==2
        first,second=data["items"]
        assert first["kind"]==second["kind"]=="run_issue"
        assert first["run_id"]==newest
        assert first["code"]=="RH_NORMALIZE_XML"
        assert first["status"]=="open"
        assert first["actionable"] is False and first["decision_actions"]==[]
        assert first["synthetic"] is True and first["outcome"]=="partial"
        assert first["issue_id"] is None and first["title"] is None
        assert second["code"]=="RH_SOURCE_PARTIAL"
        assert second["status"] is None
        assert second["message"] is None
        assert second["document_id"] is None
        assert data["unavailable_runs"]==[{"run_id":middle,"run_status":"waiting_model","issue_count":None}]

        next_page=client.get(f"/api/v1/review-inbox?limit=2&cursor={data['next_cursor']}",headers=headers)
        assert next_page.status_code==200
        assert next_page.json()["items"]==[]
        assert next_page.json()["unavailable_runs"]==[]
        assert next_page.json()["next_cursor"] is None

        unknown_scope=client.get("/api/v1/review-inbox",headers={**headers,"x-workspace-id":"unknown"})
        assert unknown_scope.status_code==404
        invalid_limit=client.get("/api/v1/review-inbox?limit=101",headers=headers)
        assert invalid_limit.status_code==400
        assert invalid_limit.json()["code"]=="RH_GUI_REVIEW_INBOX_PAGE"
