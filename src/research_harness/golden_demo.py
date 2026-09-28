"""Run the fixed synthetic Golden Demo through InvestigationService."""
from __future__ import annotations

import json
from importlib import resources
from typing import Any

from .investigation import InvestigationError, InvestigationService


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
        evidence_by_id = {item["evidence_id"]: item for item in payload.get("evidence", [])}
        def traced_claim(claim: dict[str, Any]) -> str:
            evidence_id = claim["evidence_refs"][0]
            item = evidence_by_id[evidence_id]
            locator = json.dumps(item["locator"], ensure_ascii=False, sort_keys=True)
            return (f"Claim: {claim['claim']}\n\nEvidence ID: {evidence_id}\n"
                    f"Document: {item['document_id']}\nVersion: {item['version_id']}\n"
                    f"Locator: {locator}\nSource excerpt: {claim['quote']}")
        technical = traced_claim(claims[0]) if claims else "No verified synthetic claim was available."
        review = "Cross-source synthetic evidence review.\n\n" + ("\n\n".join(traced_claim(claim) for claim in claims) or "No verified synthetic claims were available.")
        sections = []
        for kind, body, section_ids in (("technical_report", technical, ids[:1]), ("literature_review", review, ids)):
            sections.append({"deliverable_type": kind, "language": "en", "section_id": f"golden-{kind}", "title": "Synthetic offline result", "body": body, "claim_ids": section_ids})
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
        max_steps = int(runtime.get("budget", {}).get("max_tasks", 8)) + 8
        for _ in range(max_steps):
            state = service.status(run_id)
            if state["status"] in {"completed", "partial", "failed", "policy_blocked", "stopped"}:
                break
            tasks = service.get_pending_tasks(run_id)
            if not tasks:
                raise InvestigationError("RH_GOLDEN_DEMO_STALLED", "run has no pending role tasks and has not reached a terminal state")
            for task in tasks:
                service.submit_model_result(run_id, task["task_id"], _answer(task), task["task_version"])
            service.advance_investigation(run_id)
        else:
            raise InvestigationError("RH_GOLDEN_DEMO_STALLED", "run exceeded the bounded role-task progress limit")
        state = service.status(run_id)
        if state["status"] not in {"completed", "partial", "failed", "policy_blocked", "stopped"}:
            raise InvestigationError("RH_GOLDEN_DEMO_STALLED", "run did not reach a terminal state")
        service.export_report(run_id, ["en"])
        result = service.get_result(run_id)
        candidates = {item["document_id"] for page in scenario.get("transport_pages", []) for item in page.get("candidates", []) if isinstance(item, dict) and item.get("document_id")}
        return {"run_id": run_id, "outcome": result["outcome"], "synthetic": result["synthetic"], "candidate_count": len(candidates), "evidence_document_count": len({x.get("document_id") for x in result.get("evidence", [])}), "verified_claim_count": len([x for x in service.build_report_data(run_id).get("claims", []) if x.get("verification") in (True, "verified") or isinstance(x.get("verification"), dict) and x["verification"].get("status") == "verified"]), "open_issue_count": len([x for x in result.get("issues", []) if x.get("status") == "open"]), "coverage": result.get("coverage"), "artifacts": result.get("artifacts", [])}
    finally:
        if owns_service:
            service.close()
