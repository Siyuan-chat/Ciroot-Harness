import json

import pytest
import requests

from research_harness.investigation import InvestigationError, InvestigationService
from research_harness.investigation_context import build_context_bundle, verify_context_bundle
from research_harness.investigation_model_api import run_model_task
from test_investigation_c1 import SPEC, SCENARIO
from test_investigation_model_api import Reply, runtime


def test_logical_receipt_binds_task_payload_prompt_profile_without_secret():
    args = dict(run_id="run-1", task_id="task-1", task_version=1, payload={"input_refs": ["e1"], "question": "Q"},
                output_schema={"type": "object"}, prompt="instruction", profile={"model": "m"}, included_refs=["e1"],
                template_version="prompt-v1", budget={"max_model_calls": 4, "reserved_model_calls": 1},
                authorization={"result": "passed"}, retrieval_selection=None)
    first = build_context_bundle(**args)
    assert verify_context_bundle(first) and "secret" not in str(first)
    for change in ({"task_version": 2}, {"payload": {"question": "changed"}}, {"prompt": "changed"}, {"budget": {"max_model_calls": 2}}):
        assert build_context_bundle(**(args | change))["logical_sha256"] != first["logical_sha256"]


def test_atomic_context_and_response_files_are_hash_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, runtime("openai"), SCENARIO)["run_id"]
        task = service.get_pending_tasks(run)[0]
        def post(*args, **kwargs):
            payload = json.loads(kwargs["json"]["messages"][1]["content"])
            return Reply({"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]})
        with pytest.raises(InvestigationError):
            run_model_task(service, run, task, post=post)
        call_id = service.db.execute("SELECT id FROM model_api_calls").fetchone()[0]
        receipt = service.read_model_call_receipt(call_id)
        assert receipt["response_bytes"] and b"not json" in receipt["response_bytes"]
        with pytest.raises(InvestigationError): service.record_model_response(call_id, b"overwrite")
        assert service.read_model_call_receipt(call_id)["response_bytes"] == receipt["response_bytes"]
        path = tmp_path / service.db.execute("SELECT context_path FROM model_call_receipts WHERE call_id=?", (call_id,)).fetchone()[0]
        path.write_bytes(path.read_bytes() + b"x")
        with pytest.raises(InvestigationError) as error:
            service.read_model_call_receipt(call_id)
        assert error.value.code == "RH_RECEIPT_HASH"


def test_timeout_is_unknown_and_cannot_be_resent_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    service = InvestigationService(tmp_path)
    run = service.create_investigation(SPEC, runtime("openai"), SCENARIO)["run_id"]
    task = service.get_pending_tasks(run)[0]
    def timeout(*args, **kwargs): raise requests.Timeout()
    with pytest.raises(InvestigationError) as error:
        run_model_task(service, run, task, post=timeout)
    assert error.value.code == "RH_MODEL_NETWORK"
    service.close()
    with InvestigationService(tmp_path) as reopened:
        assert reopened.get_pending_tasks(run) == []
        row = reopened.db.execute("SELECT status FROM model_api_calls").fetchone()
        assert row["status"] == "outcome_unknown"
        assert reopened.status(run)["budget"]["reserved_model_calls"] == 1


def test_atomic_reservation_rejects_duplicate_task_version(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, runtime("openai"), SCENARIO)["run_id"]
        task = service.get_pending_tasks(run)[0]
        first = service.reserve_model_call(run, task["task_id"], task["task_version"])
        with pytest.raises(InvestigationError) as error:
            service.reserve_model_call(run, task["task_id"], task["task_version"])
        assert error.value.code == "RH_MODEL_CALL_IN_FLIGHT"
        assert service.status(run)["budget"]["reserved_model_calls"] == 1
        service.finish_model_call(first, "failed", None)


def test_explicit_http_error_is_recorded_and_allows_budgeted_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    config = runtime("openai"); config["budget"]["max_model_calls"] = 2
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(SPEC, config, SCENARIO)["run_id"]
        task = service.get_pending_tasks(run)[0]
        class HttpFailure:
            status_code = 429
            content = b'{"error":"rate limited"}'
        with pytest.raises(InvestigationError) as error:
            run_model_task(service, run, task, post=lambda *a, **k: HttpFailure())
        assert error.value.code == "RH_MODEL_HTTP"
        assert service.get_pending_tasks(run)[0]["task_id"] == task["task_id"]
        assert service.status(run)["budget"]["reserved_model_calls"] == 1
        call_id = service.db.execute("SELECT id FROM model_api_calls").fetchone()[0]
        assert service.db.execute("SELECT event FROM model_call_events WHERE call_id=? ORDER BY id DESC", (call_id,)).fetchone()[0] == "failed"
        assert service.reserve_model_call(run, task["task_id"], task["task_version"])


def test_dispatch_compare_and_swap_is_shared_between_service_instances(tmp_path, monkeypatch):
    import sqlite3
    import threading
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    first = InvestigationService(tmp_path)
    run = first.create_investigation(SPEC, runtime("openai"), SCENARIO)["run_id"]
    task = first.get_pending_tasks(run)[0]
    call = first.reserve_model_call(run, task["task_id"], task["task_version"])
    from research_harness.investigation_context import build_context_bundle
    ctx = build_context_bundle(run_id=run, task_id=task["task_id"], task_version=task["task_version"], payload=task["payload"],
        output_schema=task["output_schema"], prompt="p", profile={"provider":"openai"}, included_refs=[],
        template_version="v1", budget={"max_model_calls":10,"reserved_model_calls":1}, authorization={"result":"passed"})
    first.prepare_model_call(call, {"model":"m"}, ctx)
    first._lock.release()
    second = InvestigationService(tmp_path)
    try:
        first.db.close(); second.db.close()
        for service in (first, second):
            service.db=sqlite3.connect(tmp_path/"investigation.sqlite",timeout=5,check_same_thread=False)
            service.db.row_factory=sqlite3.Row
        barrier=threading.Barrier(2)
        def dispatch(service):
            barrier.wait()
            try:
                service.mark_model_call_dispatching(call); return "sent"
            except InvestigationError: return "blocked"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(dispatch,(first,second)))
        assert sorted(outcomes)==["blocked","sent"]
        assert first.db.execute("SELECT COUNT(*) FROM model_call_events WHERE call_id=? AND event='dispatching'", (call,)).fetchone()[0] == 1
    finally:
        first.db.close()
        second.close()


def test_unknown_terminal_cannot_be_overwritten_and_late_response_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    service = InvestigationService(tmp_path)
    run = service.create_investigation(SPEC, runtime("openai"), SCENARIO)["run_id"]
    task = service.get_pending_tasks(run)[0]
    with pytest.raises(InvestigationError):
        run_model_task(service, run, task, post=lambda *a, **k: (_ for _ in ()).throw(requests.Timeout()))
    call = service.db.execute("SELECT id FROM model_api_calls").fetchone()[0]
    with pytest.raises(InvestigationError): service.finish_model_call(call, "failed", None)
    with pytest.raises(InvestigationError): service.record_model_response(call, b"late")
    assert service.db.execute("SELECT status FROM model_api_calls WHERE id=?", (call,)).fetchone()[0] == "outcome_unknown"
    assert service.status(run)["budget"]["reserved_model_calls"] == 1
    service.close()


def test_accept_requires_task_result_and_prepare_failure_rolls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_RESEARCH_MODEL_KEY", "private-test-key")
    import research_harness.investigation as module
    service = InvestigationService(tmp_path)
    run = service.create_investigation(SPEC, runtime("openai"), SCENARIO)["run_id"]
    task = service.get_pending_tasks(run)[0]
    call = service.reserve_model_call(run, task["task_id"], task["task_version"])
    from research_harness.investigation_context import build_context_bundle
    ctx = build_context_bundle(run_id=run, task_id=task["task_id"], task_version=task["task_version"], payload=task["payload"],
        output_schema=task["output_schema"], prompt="prompt", profile={"provider":"openai"}, included_refs=[],
        template_version="v1", budget={"max_model_calls":10,"reserved_model_calls":1}, authorization={"result":"passed"})
    with pytest.raises(InvestigationError): service.finish_model_call(call, "accepted", None)
    monkeypatch.setattr(module.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("simulated")))
    with pytest.raises(OSError): service.prepare_model_call(call, {"model":"m"}, ctx)
    assert not service.db.in_transaction
    assert service.db.execute("SELECT status FROM model_api_calls WHERE id=?", (call,)).fetchone()[0] == "reserved"
    assert service.db.execute("SELECT 1 FROM model_call_receipts WHERE call_id=?", (call,)).fetchone() is None
    assert not list((tmp_path / "model_context").glob(call + "*"))
    service.close()
