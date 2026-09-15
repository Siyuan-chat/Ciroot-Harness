"""Real OpenAlex service integration; scripted protocol replies, not model QA."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit
import requests
from research_harness.investigation import InvestigationService

TARGET = "10.1109/access.2024.3363869"
QUERY = "Challenges and Opportunities in Green Hydrogen Adoption for Decarbonizing Hard-to-Abate Industries"


def reply(task):
    role, payload = task["role"], task["payload"]
    if role == "planning":
        return {"search_plan": {"queries": [{"query_id": "public-protocol-sample", "source": "openalex", "query": QUERY, "input_refs": [], "parent_query_id": None}]}}
    if role == "paper_search":
        assert any(x.get("doi") == TARGET for x in payload["candidates"]), "Known protocol sample was not returned"
        return {"candidates": [{"document_id": x["document_id"], "relevance": "relevant" if x.get("doi") == TARGET else "irrelevant", "reason": "Identity selection for acquisition protocol testing; not a relevance benchmark."} for x in payload["candidates"]]}
    if role == "evidence_analysis":
        assert payload["evidence"], "Live body acquisition produced no evidence"
        e = payload["evidence"][0]
        return {"findings": [{"finding_id": "f0", "finding": "A continuous excerpt is available in the acquired public document.", "evidence_ids": [e["evidence_id"]], "value": None, "unit": None, "conditions": None}]}
    if role == "business_judgment":
        return {"judgments": [{"document_id": d, "relevance": "uncertain", "human_review_required": True, "reason": "Protocol test does not assess company relevance."} for d in sorted({x["document_id"] for x in payload["documents"]})]}
    if role == "synthesis":
        e = payload["evidence"][0]
        return {"claims": [{"claim_id": "c0", "claim": "The acquired document contains the attached exact excerpt.", "finding_refs": [0], "evidence_refs": [e["evidence_id"]], "quote": e["text"][:160], "document_id": e["document_id"], "version_id": e["version_id"]}]}
    if role == "writing":
        return {"sections": [{"deliverable_type": "technical_report", "language": "en", "section_id": "protocol", "title": "Public-source protocol test", "body": "This is an integration test using real public source data and scripted task replies. It verifies acquisition and the attached excerpt only. Scientific conclusions and company relevance have not been evaluated.", "claim_ids": ["c0"]}]}
    if role == "verification":
        return {"verification": {"status": "partial", "conclusion": "Exact excerpt and source identity checked; scientific evaluation remains outside this protocol test.", "supported_claim_refs": [0]}}
    raise AssertionError("Unexpected role: " + role)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    workspace = args.output / "workspace"
    spec = {"status": "ready", "project_id": "public-source-protocol", "revision": 1,
            "research_question": "Verify public-source acquisition, citations and state propagation; scripted protocol test, not scientific assessment.",
            "report_targets": [{"deliverable_type": "technical_report", "languages": ["en"]}], "references": []}
    runtime = {"mode": "host", "data_mode": "live", "allow_network": True, "executor_id": "scripted-protocol-test",
               "budget": {"max_tasks": 10, "max_source_calls": 8, "max_pages_per_query": 2, "max_downloads": 1,
                          "max_download_calls": 12, "max_download_bytes": 10485760},
               "sources": {"openalex": {"anonymous": True, "year_min": 2020, "sort": "relevance_score:desc",
                                        "page_size": 5, "max_candidates": 10, "max_pages": 2, "timeout_seconds": 30}}}
    for name, value in (("spec", spec), ("runtime", runtime)):
        (args.output / (name + ".json")).write_text(json.dumps(value, indent=2), encoding="utf-8")
    events, roles = [], []
    original = requests.Session.request
    network_allowed = True

    def observe(session, method, url, **kwargs):
        assert network_allowed, "Completed run attempted fresh HTTP"
        start = time.perf_counter()
        event = {"host": urlsplit(url).hostname, "method": method}
        try:
            response = original(session, method, url, **kwargs)
            event["http_status"] = response.status_code
            return response
        except requests.RequestException as exc:
            event["error_type"] = type(exc).__name__
            raise
        finally:
            event["seconds"] = round(time.perf_counter()-start, 3)
            events.append(event)
            (args.output / "http.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    requests.Session.request = observe
    start = time.perf_counter()
    try:
        with InvestigationService(workspace) as service:
            run = service.create_investigation(spec, runtime)["run_id"]
            (args.output / "run-id.txt").write_text(run, encoding="utf-8")
            for _ in range(12):
                for task in service.get_pending_tasks(run):
                    roles.append(task["role"])
                    response = reply(task)
                    service.submit_model_result(run, task["task_id"], response, task["task_version"])
                service.advance_investigation(run)
                current = service.status(run)
                (args.output / "status.json").write_text(json.dumps(current, indent=2), encoding="utf-8")
                if current["outcome"] in ("completed", "partial") and not service.get_pending_tasks(run):
                    break
            result = service.get_result(run)
            assert result["synthetic"] is False
            assert len(set(roles)) == 7, roles
            assert any(e["locator"]["kind"] == "pdf_page" for e in result["evidence"])
            frozen = service.build_report_data(run)
            assert frozen["synthetic"] is False
            exported = service.export_report(run)
            artifacts = exported["artifacts"]
            assert any(x["format"] == "markdown" for x in artifacts)
            digests = {x["path"]: hashlib.sha256((workspace/x["path"]).read_bytes()).hexdigest() for x in artifacts}
            before = copy.deepcopy(service.status(run)["budget"])
            source_calls = sum(e["host"] == "api.openalex.org" for e in events)
            assert before["reserved_source_calls"] == source_calls
        network_allowed = False
        with InvestigationService(workspace) as service:
            service.resume_investigation(run)
            service.export_report(run)
            assert service.status(run)["budget"] == before
            assert service.build_report_data(run) == frozen
            assert all(hashlib.sha256((workspace/path).read_bytes()).hexdigest() == digest for path, digest in digests.items())
            status = service.status(run)
        report = {"status": "passed", "run_id": run, "roles": roles, "seconds": round(time.perf_counter()-start, 3),
                  "model_results": "scripted protocol replies; not Luna/science acceptance", "source_http_calls": source_calls,
                  "budget": before, "result": result, "source_state": status["coverage"], "artifacts": artifacts,
                  "restart": "no new HTTP; budgets and report bytes preserved"}
        (args.output / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ("status", "run_id", "roles", "seconds", "source_http_calls", "restart")}))
    finally:
        requests.Session.request = original


if __name__ == "__main__":
    main()
