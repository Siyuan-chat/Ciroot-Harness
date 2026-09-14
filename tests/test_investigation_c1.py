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
    if role == "planning": return {"search_plan":{"queries":[{"query_id":"paper-query","source":"synthetic-paper","query":"synthetic crosslinking membrane","input_refs":[],"parent_query_id":None},{"query_id":"patent-query","source":"synthetic-patent","query":"synthetic crosslinked polymer","input_refs":[],"parent_query_id":None}]}}
    if role in ("paper_search", "patent_search"):
        return {"candidates": [{"document_id": c["document_id"], "relevance": "relevant", "reason": "matches synthetic plan"} for c in p["candidates"]]}
    if role == "evidence_analysis": return {"findings": [{"finding_id":"f0","finding": "Synthetic evidence was extracted.", "evidence_ids": [p["evidence"][0]["evidence_id"]],"value":None,"unit":None,"conditions":None}]}
    if role == "business_judgment": return {"judgments": [{"document_id": d["document_id"], "relevance": "relevant", "human_review_required": False, "reason": "synthetic scope"} for d in p["documents"]]}
    if role == "synthesis":
        evidence=p["evidence"][0]
        return {"claims": [{"claim_id":"c0","claim":evidence["text"],"finding_refs":[0],"evidence_refs":[evidence["evidence_id"]],"quote":evidence["text"],"document_id":evidence["document_id"],"version_id":evidence["version_id"]}]}
    if role == "writing": return {"sections": [{"deliverable_type":kind,"language":"en","section_id":kind,"title":"Synthetic result","body":"The supplied synthetic evidence supports the route.","claim_ids":["c0"]} for kind in ("technical_report","literature_review")]}
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

def test_c2_invalid_planning_lineage_and_source_do_not_consume_task(tmp_path):
    service = InvestigationService(tmp_path); run = service.create_investigation(SPEC, RUNTIME, SCENARIO)["run_id"]
    task = service.get_pending_tasks(run)[0]
    for query in (
        {"query_id":"loop","source":"synthetic-paper","query":"synthetic","input_refs":[],"parent_query_id":"loop"},
        {"query_id":"remote","source":"unsupported-source","query":"synthetic","input_refs":[],"parent_query_id":None},
    ):
        with pytest.raises(InvestigationError): service.submit_model_result(run, task["task_id"], {"search_plan":{"queries":[query]}}, task["task_version"])
        assert service.get_pending_tasks(run)[0]["task_id"] == task["task_id"]
    assert service.validate_plan({"search_plan":{"queries":[{"query_id":"p","source":"synthetic-paper","query":"synthetic","input_refs":[],"parent_query_id":None}]}})["valid"] is True

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

def test_c2_normalization_failure_is_frozen_and_partial(tmp_path):
    scenario = json.loads(json.dumps(SCENARIO))
    scenario["sources"][1].update(content_type="application/pdf", base64_bytes="bm90IGEgcGRm")
    service = InvestigationService(tmp_path); run = service.create_investigation(SPEC, RUNTIME, scenario)["run_id"]
    while service.status(run)["outcome"] not in ("completed", "partial"):
        for task in service.get_pending_tasks(run):
            service.submit_model_result(run, task["task_id"], answer(task), task["task_version"])
        service.advance_investigation(run)
    result = service.get_result(run); report = service.build_report_data(run)
    assert result["outcome"] == "partial"
    assert any(issue["code"] == "RH_NORMALIZE_PDF" for issue in result["issues"])
    assert report["issues"] == result["issues"]
    assert any(item["document_id"] == "paper-001" for item in result["evidence"])
