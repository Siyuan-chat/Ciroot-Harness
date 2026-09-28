"""Run the fixed synthetic Golden Demo through InvestigationService."""
from __future__ import annotations

import json
from importlib import resources
from typing import Any

from .investigation import InvestigationService


def _answer(task: dict[str, Any]) -> dict[str, Any]:
    role, payload = task["role"], task["payload"]
    if role == "planning":
        return {"search_plan": {"queries": [
            {"query_id": "paper-query", "source": "synthetic-paper", "query": "synthetic membrane crosslinking", "input_refs": [], "parent_query_id": None},
            {"query_id": "patent-query", "source": "synthetic-patent", "query": "synthetic crosslinked membrane", "input_refs": [], "parent_query_id": None},
        ]}}
    if role in {"paper_search", "patent_search"}:
        return {"candidates": [{"document_id": item["document_id"], "relevance": "relevant", "reason": "Included in the fixed synthetic scenario."} for item in payload["candidates"]]}
    if role == "evidence_analysis":
        return {"findings": [{"finding_id": f"golden-finding-{i+1}", "finding": "Synthetic source statement retained for review.", "evidence_ids": [item["evidence_id"]], "value": None, "unit": None, "conditions": None} for i, item in enumerate(payload["evidence"])]}
    if role == "business_judgment":
        return {"judgments": [{"document_id": item["document_id"], "relevance": "uncertain" if item["document_id"] == "paper-001" else "relevant", "human_review_required": item["document_id"] == "paper-001", "reason": "Synthetic relevance flag; researcher review is required." if item["document_id"] == "paper-001" else "Synthetic scope match."} for item in payload["documents"]]}
    if role == "synthesis":
        claims = []
        for i, item in enumerate(payload["evidence"]):
            claims.append({"claim_id": f"golden-claim-{i+1}", "claim": item["text"], "finding_refs": [i], "evidence_refs": [item["evidence_id"]], "quote": item["text"], "document_id": item["document_id"], "version_id": item["version_id"]})
        return {"claims": claims}
    if role == "writing":
        claims = payload.get("claims", [])
        ids = [item["claim_id"] for item in claims]
        sections = []
        for kind in ("technical_report", "literature_review"):
            sections.append({"deliverable_type": kind, "language": "en", "section_id": f"golden-{kind}", "title": "Synthetic offline result", "body": "This report contains only the supplied synthetic statements and their verified evidence links.", "claim_ids": ids})
        return {"sections": sections}
    if role == "verification":
        claims = payload.get("claims", [])
        return {"verification": {"status": "supported" if claims else "insufficient", "conclusion": "All emitted claims bind to the supplied synthetic evidence." if claims else "No claims were emitted.", "supported_claim_refs": list(range(len(claims)))}}
    raise ValueError(f"unsupported deterministic role: {role}")


def run_golden_demo(workspace: str, service: InvestigationService | None = None) -> dict[str, Any]:
    base = resources.files("research_harness").joinpath("examples", "investigation")
    spec = json.loads(base.joinpath("golden-demo-spec.json").read_text(encoding="utf-8-sig"))
    runtime = json.loads(base.joinpath("synthetic-runtime.json").read_text(encoding="utf-8-sig"))
    scenario = json.loads(base.joinpath("golden-demo-scenario.json").read_text(encoding="utf-8-sig"))
    owns_service = service is None
    service = service or InvestigationService(workspace)
    try:
        run_id = service.create_investigation(spec, runtime, scenario)["run_id"]
        while True:
            state = service.status(run_id)
            if state["status"] in {"completed", "partial", "failed", "policy_blocked", "stopped"}:
                break
            tasks = service.get_pending_tasks(run_id)
            for task in tasks:
                service.submit_model_result(run_id, task["task_id"], _answer(task), task["task_version"])
            service.advance_investigation(run_id)
        service.export_report(run_id, ["en"])
        result = service.get_result(run_id)
        return {"run_id": run_id, "outcome": result["outcome"], "synthetic": result["synthetic"], "candidate_count": len({x.get("document_id") for x in result.get("evidence", [])}), "verified_claim_count": len([x for x in service.build_report_data(run_id).get("claims", []) if x.get("verification") in (True, "verified") or isinstance(x.get("verification"), dict) and x["verification"].get("status") == "verified"]), "open_issue_count": len([x for x in result.get("issues", []) if x.get("status") == "open"]), "coverage": result.get("coverage"), "artifacts": result.get("artifacts", [])}
    finally:
        if owns_service:
            service.close()
