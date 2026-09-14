import json
from pathlib import Path
import pytest
from research_harness.investigation import InvestigationError, InvestigationService

ROOT = Path(__file__).parents[1] / "examples" / "investigation"
SPEC = json.loads((ROOT / "synthetic-spec.json").read_text())
RUNTIME = json.loads((ROOT / "synthetic-runtime.json").read_text())
SCENARIO = json.loads((ROOT / "synthetic-scenario.json").read_text())

def answer(task):
    role, p = task["role"], task["payload"]
    if role == "planning": return json.loads((ROOT / "planning-result.json").read_text())
    if role in ("paper_search", "patent_search"):
        return {"candidates": [{"document_id": c["document_id"], "relevance": "relevant", "reason": "matches synthetic plan"} for c in p["candidates"]]}
    if role == "evidence_analysis": return {"findings": [{"finding": "Synthetic evidence was extracted.", "evidence_ids": [p["evidence"][0]["evidence_id"]]}]}
    if role == "business_judgment": return {"judgments": [{"document_id": d["document_id"], "relevance": "relevant", "human_review_required": False, "reason": "synthetic scope"} for d in p["documents"]]}
    if role == "synthesis": return {"claims": [{"claim": "The synthetic route has documented evidence.", "finding_refs": [0]}]}
    if role == "writing": return {"sections": [{"title": "Synthetic result", "text": "The supplied synthetic evidence supports the route.", "claim_refs": [0]}]}
    return {"verification": {"status": "supported", "conclusion": "Supported by normalized synthetic evidence.", "supported_claim_refs": [0]}}

def finish(service, run):
    while service.status(run)["status"] != "completed":
        for task in service.get_pending_tasks(run):
            result = answer(task)
            assert service.submit_model_result(run, task["task_id"], result, task["task_version"])["status"] == "accepted"
        service.advance_investigation(run)

def test_c1_valid_chain_is_real_and_persistent(tmp_path):
    service = InvestigationService(tmp_path)
    run = service.create_investigation(SPEC, RUNTIME, SCENARIO)["run_id"]
    first = service.get_pending_tasks(run)[0]
    assert service.submit_model_result(run, first["task_id"], answer(first), first["task_version"])["status"] == "accepted"
    assert service.submit_model_result(run, first["task_id"], answer(first), first["task_version"])["status"] == "reused"
    service.advance_investigation(run)
    assert {x["role"] for x in service.get_pending_tasks(run)} == {"paper_search", "patent_search"}
    service.close(); service = InvestigationService(tmp_path)
    finish(service, run)
    state, result = service.status(run), service.get_result(run)
    assert [x["node"] for x in state["stage_trace"]] == ["planning_gate", "source_task", "acquire_normalize", "analysis_task", "verification_gate"]
    assert result["conclusion"] == "Supported by normalized synthetic evidence."
    assert result["findings"][0]["evidence_ids"]

def test_c1_bad_results_do_not_consume_task(tmp_path):
    service = InvestigationService(tmp_path); run = service.create_investigation(SPEC, RUNTIME, SCENARIO)["run_id"]
    task = service.get_pending_tasks(run)[0]
    with pytest.raises(InvestigationError): service.submit_model_result(run, task["task_id"], {"search_plan": {}}, task["task_version"])
    assert service.get_pending_tasks(run)[0]["task_id"] == task["task_id"]

def test_c1_budget_is_reserved_before_task_creation(tmp_path):
    runtime = {"mode": "host", "data_mode": "synthetic", "budget": {"max_tasks": 1}}
    service = InvestigationService(tmp_path); run = service.create_investigation(SPEC, runtime, SCENARIO)["run_id"]
    task = service.get_pending_tasks(run)[0]
    service.submit_model_result(run, task["task_id"], answer(task), task["task_version"])
    assert service.advance_investigation(run)["outcome"] == "partial"
    assert service.status(run)["budget"]["reserved_tasks"] == 1

def test_c1_two_source_reservation_is_atomic(tmp_path):
    runtime = {"mode": "host", "data_mode": "synthetic", "budget": {"max_tasks": 2}}
    service = InvestigationService(tmp_path); run = service.create_investigation(SPEC, runtime, SCENARIO)["run_id"]
    task = service.get_pending_tasks(run)[0]; service.submit_model_result(run, task["task_id"], answer(task), task["task_version"])
    assert service.advance_investigation(run)["outcome"] == "partial"
    assert service.status(run)["stage"] == "budget_exhausted"
    assert service.status(run)["budget"]["reserved_tasks"] == 1
    assert service.get_pending_tasks(run) == []

def test_c1_non_supported_verification_is_partial(tmp_path):
    service = InvestigationService(tmp_path); run = service.create_investigation(SPEC, RUNTIME, SCENARIO)["run_id"]
    while service.status(run)["stage"] != "verification" or not any(x["role"] == "verification" for x in service.get_pending_tasks(run)):
        for task in service.get_pending_tasks(run):
            service.submit_model_result(run, task["task_id"], answer(task), task["task_version"])
        service.advance_investigation(run)
    task = service.get_pending_tasks(run)[0]
    partial = {"verification": {"status": "insufficient", "conclusion": "Evidence remains insufficient.", "supported_claim_refs": []}}
    service.submit_model_result(run, task["task_id"], partial, task["task_version"])
    assert service.advance_investigation(run)["outcome"] == "partial"
    assert service.status(run)["outcome"] == "partial"
    assert service.get_result(run)["outcome"] == "partial"
