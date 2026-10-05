import json
import json as json_module
import hashlib
import re

import pytest
from pathlib import Path

from research_harness.investigation import InvestigationError, InvestigationService
from research_harness.research_engine_gateway import (_decode_engine_text, _engine_provider_request,
    _findings_from_resolved, run_research_engine_task)
from research_harness.investigation_model_api import advance_api_run
from test_investigation_c1 import SPEC, SCENARIO, answer


def explicit_legacy_scenario():
    return {**SCENARIO, "sources": [{**item, "legacy_unversioned": True} for item in SCENARIO["sources"]]}


def test_gateway_refuses_unconfigured_engine_before_claiming_task(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "test-key")
    runtime = {"mode": "api", "data_mode": "synthetic", "allow_network": True,
        "model_api": {"provider": "deepseek", "model": "unit-model", "api_key_env": "TEST_KEY", "max_output_tokens": 64, "timeout_seconds": 3},
        "budget": {"max_tasks": 10, "max_model_calls": 4},
        "research_engine": {"name": "paperqa", "python_executable": str(tmp_path / "missing.exe"), "embedding_model": "embed-v1", "timeout_seconds": 3}}
    with InvestigationService(tmp_path / "ws") as service:
        run = service.create_investigation(SPEC, runtime, SCENARIO)["run_id"]
        task = service.get_pending_tasks(run)[0]
        with pytest.raises(InvestigationError, match="runtime is unavailable"):
            run_research_engine_task(service, run, task, post=lambda *_a, **_k: pytest.fail("must not call provider"))
        assert service.db.execute("SELECT count(*) FROM engine_task_leases").fetchone()[0] == 0


def test_engine_task_lease_and_child_calls_share_existing_call_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "test-key")
    runtime = {"mode": "api", "data_mode": "synthetic", "allow_network": True,
        "model_api": {"provider": "deepseek", "model": "unit-model", "api_key_env": "TEST_KEY", "max_output_tokens": 64, "timeout_seconds": 3},
        "budget": {"max_tasks": 10, "max_model_calls": 2}}
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, runtime, SCENARIO)["run_id"]
        task = service.get_pending_tasks(run)[0]
        lease = service.reserve_engine_lease(run, task["task_id"], task["task_version"])
        with pytest.raises(InvestigationError, match="already has an engine lease"):
            service.reserve_engine_lease(run, task["task_id"], task["task_version"])
        service.mark_engine_dispatching(lease)
        call = service.reserve_engine_model_call(lease, "request-1", "embedding", "test")
        assert service.status(run)["budget"]["reserved_model_calls"] == 1
        assert service.db.execute("SELECT kind FROM engine_model_calls WHERE call_id=?", (call,)).fetchone()[0] == "embedding"
        with pytest.raises(InvestigationError, match="unresolved broker call"):
            service.reserve_engine_model_call(lease, "request-2", "model_call", "test")
        budget_before = service.status(run)["budget"]["reserved_model_calls"]
        with pytest.raises(InvestigationError, match="already reserved"):
            service.reserve_engine_model_call(lease, "request-1", "embedding", "test")
        assert service.status(run)["budget"]["reserved_model_calls"] == budget_before
        rpc={"op":"embedding","request":{"model":"offline-test","texts":[]}}
        context=service.engine_context(run,task,rpc,{"provider":"local"})
        service.prepare_model_call(call,{"model":"offline-test","texts":[]},context)
        service.mark_model_call_dispatching(call)
        service.finish_model_call(call,"failed",None)  # dispatching -> outcome_unknown
        service.finish_engine_lease(lease,"failed")  # unresolved child forces parent unknown
        assert service.get_pending_tasks(run) == []
    with InvestigationService(tmp_path) as reopened:
        assert reopened.get_pending_tasks(run) == []
        assert reopened.status(run)["budget"]["reserved_model_calls"] == 1
        assert reopened.db.execute("SELECT status FROM engine_task_leases").fetchone()[0] == "outcome_unknown"


def test_child_call_reservation_rolls_back_budget_and_rows_on_mapping_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "test-key")
    runtime = {"mode": "api", "data_mode": "synthetic", "allow_network": True,
        "model_api": {"provider":"deepseek","model":"unit-model","api_key_env":"TEST_KEY","max_output_tokens":64,"timeout_seconds":3},
        "budget": {"max_tasks": 10, "max_model_calls": 1}}
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, runtime, SCENARIO)["run_id"]
        task = service.get_pending_tasks(run)[0]
        lease = service.reserve_engine_lease(run, task["task_id"], task["task_version"])
        service.mark_engine_dispatching(lease)
        service.db.execute("CREATE TRIGGER fail_engine_map BEFORE INSERT ON engine_model_calls BEGIN SELECT RAISE(ABORT,'injected mapping failure'); END")
        service.db.commit()
        with pytest.raises(Exception, match="injected mapping failure"):
            service.reserve_engine_model_call(lease, "request-fail", "model_call", "test")
        assert service.status(run)["budget"]["reserved_model_calls"] == 0
        assert service.db.execute("SELECT count(*) FROM model_api_calls").fetchone()[0] == 0
        service.db.execute("DROP TRIGGER fail_engine_map")
        service.db.commit()
        call = service.reserve_engine_model_call(lease, "request-ok", "model_call", "test")
        assert service.status(run)["budget"]["reserved_model_calls"] == 1
        service.finish_model_call(call, "failed", None)
        with pytest.raises(InvestigationError, match="cannot accept another response"):
            service.record_model_response(call, b"late response")
        with pytest.raises(InvestigationError, match="budget exhausted"):
            service.reserve_engine_model_call(lease, "request-last", "model_call", "test")
        assert service.db.execute("SELECT count(*) FROM engine_model_calls").fetchone()[0] == 1
        assert service.db.execute("SELECT call_id FROM engine_model_calls").fetchone()[0] == call


def test_engine_lease_acceptance_requires_task_result_and_no_pending_child_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "test-key")
    runtime = {"mode":"api","data_mode":"synthetic","allow_network":True,
        "model_api":{"provider":"deepseek","model":"unit-model","api_key_env":"TEST_KEY","max_output_tokens":64,"timeout_seconds":3},
        "budget":{"max_tasks":10,"max_model_calls":3}}
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, runtime, SCENARIO)["run_id"]
        task = service.get_pending_tasks(run)[0]
        lease = service.reserve_engine_lease(run, task["task_id"], task["task_version"])
        service.mark_engine_dispatching(lease)
        call = service.reserve_engine_model_call(lease, "accepted-rpc", "model_call", "test")
        rpc = {"op":"model_call","request":{"messages":[{"role":"user","content":"test"}]}}
        service.prepare_model_call(call, {"messages":[{"role":"user","content":"test"}]}, service.engine_context(run, task, rpc, runtime["model_api"], {"result":"passed"}))
        service.mark_model_call_dispatching(call)
        service.record_model_response(call, b'{"complete":true}')
        service.finish_model_call(call, "accepted", {"output_tokens":1})
        with pytest.raises(InvestigationError, match="accepted task result"):
            service.finish_engine_lease(lease, "accepted")
        second = service.reserve_engine_model_call(lease, "pending-rpc", "model_call", "test")
        with pytest.raises(InvestigationError, match="unresolved child calls"):
            service.finish_engine_lease(lease, "accepted")
        service.finish_model_call(second, "failed", None)
        output = answer({"role": task["role"], "payload": task["payload"]})
        service.submit_model_result(run, task["task_id"], output, task["task_version"])
        service.finish_engine_lease(lease, "accepted")
        assert service.db.execute("SELECT status FROM engine_task_leases WHERE id=?", (lease,)).fetchone()[0] == "accepted"


def test_engine_findings_use_only_each_claims_exact_resolved_citations():
    from research_harness.research_engines import resolve_engine_citations
    a = {"evidence_id":"ev-a", "document_id":"doc-a", "version_id":"v1", "parse_revision_id":"p1", "locator":"p.1", "text":"Alpha result was 12 MPa under these conditions."}
    b = {"evidence_id":"ev-b", "document_id":"doc-b", "version_id":"v2", "parse_revision_id":"p2", "locator":"p.2", "text":"Beta result was 8 MPa under these conditions."}
    legacy_unmarked = {"evidence_id":"ev-old", "document_id":"doc-old", "version_id":"v0", "locator":"p.3", "text":"Unversioned legacy passage has a unique quote."}
    envelope = {"run_id":"r", "task":{"task_id":"t", "task_version":1}, "evidence":[a,b,legacy_unmarked]}
    result = {"draft":{"sections":[],"coverage_gaps":[],"claims":[
        {"text":"Alpha was 12 MPa.","citation_ids":["ca"]},
        {"text":"Beta was 8 MPa.","citation_ids":["cb"]},
        {"text":"Unsupported statement.","citation_ids":[]},
        {"text":"Wrong publication.","citation_ids":["bad"]},
        {"text":"Missing parse revision.","citation_ids":["cm"]}],
        "citations":[
            {"citation_id":"ca","evidence_id":"ev-a","document_id":"doc-a","version_id":"v1","parse_revision_id":"p1","locator":"p.1","quote":"Alpha result was 12 MPa"},
            {"citation_id":"cb","evidence_id":"ev-b","document_id":"doc-b","version_id":"v2","parse_revision_id":"p2","locator":"p.2","quote":"Beta result was 8 MPa"},
            {"citation_id":"bad","evidence_id":"ev-a","document_id":"doc-b","version_id":"v2","parse_revision_id":"p1","locator":"p.2","quote":"Alpha result was 12 MPa"},
            {"citation_id":"cm","evidence_id":"ev-old","document_id":"doc-old","version_id":"v0","locator":"p.3","quote":"Unversioned legacy passage"}]}}
    resolved = resolve_engine_citations(envelope, result)
    findings, excluded = _findings_from_resolved(resolved)
    assert [item["evidence_ids"] for item in findings] == [["ev-a"], ["ev-b"]]
    assert len(excluded) == 3
    assert any(item["code"] == "RH_ENGINE_EVIDENCE_IDENTITY" for item in resolved["issues"])
    assert any(item["code"] == "RH_ENGINE_PARSE_REVISION" for item in resolved["issues"])


def test_engine_text_provider_preserves_messages_and_accepts_text_or_json_summary(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret")
    rpc = {"request":{"model":"engine-model","messages":[{"role":"system","content":"full system prompt"},{"role":"user","content":"prompt asking for JSON summary"}],"max_output_tokens":32}}
    runtime = {"model_api":{"provider":"deepseek","model":"configured-model","api_key_env":"TEST_KEY","max_output_tokens":64}}
    endpoint, headers, body = _engine_provider_request(rpc, runtime)
    assert body["messages"] == rpc["request"]["messages"]
    assert body["max_tokens"] == 32 and "secret" not in json.dumps(body)
    capped = {"request": {**rpc["request"], "max_output_tokens": 1024}}
    assert _engine_provider_request(capped, runtime)[2]["max_tokens"] == 64
    with pytest.raises(InvestigationError, match="positive integer"):
        _engine_provider_request({"request": {**rpc["request"], "max_output_tokens": True}}, runtime)
    text, _ = _decode_engine_text("deepseek", type("R", (), {"json":lambda self:{"choices":[{"finish_reason":"stop","message":{"content":json_module.dumps({"summary":"kept"})}}],"usage":{}}})())
    assert json.loads(text)["summary"] == "kept"
    text, _ = _decode_engine_text("deepseek", type("R", (), {"json":lambda self:{"choices":[{"finish_reason":"stop","message":{"content":"ordinary PaperQA prose"}}],"usage":{}}})())
    assert text == "ordinary PaperQA prose"
    anth = {"model_api":{"provider":"anthropic","model":"anthropic-model","api_key_env":"TEST_KEY","max_output_tokens":64}}
    _, _, anthropic_body = _engine_provider_request(rpc, anth)
    assert anthropic_body["system"] == "full system prompt" and anthropic_body["messages"] == [{"role":"user","content":"prompt asking for JSON summary"}]
    with pytest.raises(InvestigationError, match="complete PaperQA text"):
        _decode_engine_text("deepseek", type("R", (), {"json":lambda self:{"choices":[{"finish_reason":"length","message":{"content":"partial"}}]}})())


def test_paperqa_engine_advances_offline_run_exports_and_reopens(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    paperqa_python = root / ".local" / "integration-20261005" / "paperqa-runtime" / "Scripts" / "python.exe"
    embed_python = root / ".local" / "gui-clean-venv" / "Scripts" / "python.exe"
    embed_cache = root / ".local" / "rag-acceptance" / "luna-e5-small-probe" / "model-cache"
    if not paperqa_python.is_file() or not embed_python.is_file() or not embed_cache.is_dir():
        pytest.skip("frozen local runtime or embedding cache is unavailable")
    monkeypatch.setenv("TEST_KEY", "offline-only-key")
    runtime = {"mode": "api", "data_mode": "synthetic", "allow_network": True,
        "model_api": {"provider": "deepseek", "model": "unit-model", "api_key_env": "TEST_KEY", "max_output_tokens": 96, "timeout_seconds": 8},
        "budget": {"max_tasks": 20, "max_model_calls": 24},
        "research_engine": {"name": "paperqa", "python_executable": str(paperqa_python), "embedding_model": "multilingual-e5-small", "timeout_seconds": 60,
            "local_embedding": {"python_executable": str(embed_python), "model": "intfloat/multilingual-e5-small", "cache_dir": str(embed_cache)}}}
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, runtime, explicit_legacy_scenario())["run_id"]
        # Real local FastEmbed execution is retained; provider chat calls remain mocked.
        def post(url, *, headers, json, timeout, allow_redirects):
            prompt = "\n".join(message["content"] for message in json["messages"])
            try:
                payload = json_module.loads(json["messages"][1]["content"])
                if isinstance(payload, dict) and payload.get("role") and isinstance(payload.get("payload"), dict):
                    result = answer({"role": payload["role"], "payload": payload["payload"]})
                    text = json_module.dumps(result, ensure_ascii=False)
                    data = {"choices": [{"finish_reason": "stop", "message": {"content": text}}], "usage": {}}
                    return type("Reply", (), {"status_code": 200, "content": json_module.dumps(data).encode(), "json": lambda self: data})()
            except (ValueError, KeyError, TypeError):
                pass
            ids = re.findall(r"pqac-[A-Za-z0-9_-]+", prompt)
            if "JSON" in prompt or "json" in prompt.lower():
                docs = re.findall(r"evidence-\d+-ev-[A-Za-z0-9]+", prompt)
                text = json_module.dumps({"summary": "Summary for " + (docs[0] if docs else "the supplied passage"), "score": 5})
            else:
                text = "The supplied frozen passage reports the tested result." + (f" ({ids[0]})" if ids else "")
            data = {"choices": [{"finish_reason": "stop", "message": {"content": text}}], "usage": {}}
            return type("Reply", (), {"status_code": 200, "content": json_module.dumps(data).encode(), "json": lambda self: data})()
        status = advance_api_run(service, run, post=post)
        assert status["status"] in {"partial", "completed"} and status["stage"] == "completed"
        assert service.get_artifacts(run)
        assert service.db.execute("SELECT count(*) FROM engine_task_leases").fetchone()[0] == 1
        assert service.db.execute("SELECT count(*) FROM engine_model_calls WHERE kind='embedding'").fetchone()[0] >= 1
        assert service.db.execute("SELECT count(*) FROM engine_receipts WHERE run_id=?", (run,)).fetchone()[0] == 1
        receipt_id = service.db.execute("SELECT id FROM engine_receipts WHERE run_id=?", (run,)).fetchone()[0]
        engine_receipt = service.read_engine_receipt(receipt_id)
        assert engine_receipt["authorization"]["result"] == "passed"
        assert engine_receipt["engine_result"]["draft"]["claims"]
        valid_citations = {item["citation_id"] for item in engine_receipt["resolution"]["validated"]["citations"]}
        assert valid_citations
        assert all(set(claim["citation_ids"]) <= valid_citations for claim in engine_receipt["resolution"]["validated"]["claims"])
        assert {item["citation_id"].removeprefix("paperqa-") for item in engine_receipt["resolution"]["validated"]["citations"]} == set(engine_receipt["engine_result"]["trace"]["used_context_ids"])
        reserved = service.status(run)["budget"]["reserved_model_calls"]
        report = service.build_report_data(run)
        assert any(item.get("code") == "RH_ENGINE_COVERAGE_GAP" for item in report.get("issues", []))
    with InvestigationService(tmp_path) as reopened:
        assert advance_api_run(reopened, run, post=post)["status"] == status["status"]
        assert reopened.status(run)["budget"]["reserved_model_calls"] == reserved
        assert reopened.build_report_data(run) == report
        receipt_id = reopened.db.execute("SELECT id FROM engine_receipts WHERE run_id=?", (run,)).fetchone()[0]
        engine_receipt = reopened.read_engine_receipt(receipt_id)
        assert engine_receipt["resolution"]["validated"]["claims"]
        engine_receipt_sha = reopened.db.execute("SELECT sha256 FROM engine_receipts WHERE id=?", (receipt_id,)).fetchone()[0]
        calls = [dict(row) for row in reopened.db.execute("SELECT e.call_id,e.kind,e.purpose,m.status FROM engine_model_calls e JOIN model_api_calls m ON m.id=e.call_id WHERE e.lease_id IN (SELECT id FROM engine_task_leases WHERE run_id=?) ORDER BY m.created", (run,))]
        receipts=[]
        for call in calls:
            saved=reopened.read_model_call_receipt(call["call_id"])
            assert saved["response_bytes"] is not None
            assert "offline-only-key" not in json.dumps(saved["request_body"], ensure_ascii=False)
            receipts.append({"call_id":call["call_id"],"status":saved["status"],"response_present":True})
        saved_model_context = [reopened.read_model_call_receipt(call["call_id"]) for call in calls if call["kind"] == "model"]
        assert saved_model_context and any(item["context"]["authorization"]["result"] == "passed" for item in saved_model_context)
        assert any(item["context"]["retrieval_selection"]["selection_status"] == "context_ids_available" for item in saved_model_context)
        used_context_id = engine_receipt["engine_result"]["trace"]["used_context_ids"][0]
        assert any(used_context_id in item["context"]["retrieval_selection"]["request_selection"]["paperqa_context_ids_in_request"] for item in saved_model_context if item["context"]["retrieval_selection"]["selection_status"] == "context_ids_available")
        extract = reopened.db.execute("SELECT result FROM model_tasks WHERE run_id=? AND role='evidence_analysis' AND task_type='extract'", (run,)).fetchone()
        artifact_rows = reopened.get_artifacts(run)
        record = {"validation": "offline_engineering_only", "scientific_support": "not_assessed", "run_id": run,
            "status": status["status"], "stage": status["stage"], "reserved_model_calls": reserved,
            "engine": {"package": "paper-qa", "version": "2026.8.12", "wheel_sha256": "4cdf007207dea58edf1c1f3507ca33e1e7737fd8d7a17cb1736a8a089463918c",
                "embedding_model": "intfloat/multilingual-e5-small", "embedding_dimensions": 384,
                "transport": "mock core provider; local embedding executed offline", "worker_network_guard": "application-level socket/DNS/connect denied"},
            "engine_calls": calls, "response_receipts": receipts,
            "engine_receipt": {"id": receipt_id, "sha256": engine_receipt_sha,
                "claims": engine_receipt["resolution"]["validated"]["claims"],
                "citations": engine_receipt["resolution"]["validated"]["citations"],
                "issues": engine_receipt["resolution"]["issues"]},
            "extract_findings": json.loads(extract["result"])["findings"] if extract and extract["result"] else [],
            "report_data_sha256": hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "artifacts": artifact_rows}
        output = root / ".local" / "integration-20261005" / "paperqa-offline-smoke"
        output.mkdir(parents=True, exist_ok=True)
        (output / "acceptance.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
