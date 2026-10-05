import json
import os
import sqlite3

import pytest
from jsonschema import Draft202012Validator

from research_harness.patent_source_gateway import PatentSourceGateway


class FakeService:
    def __init__(self, root):
        from pathlib import Path
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "investigation.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS investigations(id TEXT PRIMARY KEY,spec TEXT,runtime TEXT,scenario TEXT,status TEXT,stage TEXT,budget TEXT,created REAL,updated REAL,result TEXT,trace TEXT);
        CREATE TABLE IF NOT EXISTS model_tasks(id TEXT PRIMARY KEY,run_id TEXT,task_version INTEGER,role TEXT,task_type TEXT,payload TEXT,status TEXT);
        CREATE TABLE IF NOT EXISTS source_queries(run_id TEXT,query_id TEXT,source TEXT,query TEXT,parent_query_id TEXT,input_refs TEXT,status TEXT,reason TEXT,PRIMARY KEY(run_id,query_id));
        CREATE TABLE IF NOT EXISTS source_attempts(run_id TEXT,query_id TEXT,cursor TEXT,attempt INTEGER,status TEXT,result TEXT,PRIMARY KEY(run_id,query_id,cursor,attempt));
        CREATE TABLE IF NOT EXISTS source_query_details(run_id TEXT,query_id TEXT,payload TEXT NOT NULL,PRIMARY KEY(run_id,query_id));
        CREATE TABLE IF NOT EXISTS engine_task_leases(id TEXT,run_id TEXT,task_id TEXT,task_version INTEGER,status TEXT);
        CREATE TABLE IF NOT EXISTS model_api_calls(id TEXT PRIMARY KEY,run_id TEXT NOT NULL,task_id TEXT NOT NULL,task_version INTEGER NOT NULL,status TEXT NOT NULL,usage TEXT,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS discovery_evidence(evidence_id TEXT,run_id TEXT,document_id TEXT,version_id TEXT,payload TEXT,visibility TEXT,company_id TEXT);
        CREATE TABLE IF NOT EXISTS discovery_documents(run_id TEXT,document_id TEXT,payload TEXT);
        """)
        runtime = {
            "data_mode": "live", "allow_network": True,
            "data_policy": {"allow_query_egress": True},
            "budget": {"max_source_calls": 3, "max_source_bytes": 10000,
                       "max_source_response_bytes": 4096, "max_download_calls": 2,
                       "max_download_bytes": 5000},
            "patent_sources": {
                "jpo": {"enabled": True, "capabilities": ["case_progress"], "max_calls": 2,
                        "max_response_bytes": 4096, "token_env": "TEST_JPO_TOKEN"},
                "tipo_opd": {"enabled": True, "capabilities": ["case_lookup"], "max_calls": 1, "max_response_bytes": 1024},
                "wipo_pearl": {"enabled": True, "capabilities": ["terminology_search"], "max_calls": 1, "max_response_bytes": 1024},
            },
        }
        budget = {"max_source_calls": 3, "reserved_source_calls": 0,
                  "reserved_source_bytes": 0, "received_source_bytes": 0,
                  "reserved_download_calls": 0, "reserved_download_bytes": 0,
                  "received_download_bytes": 0}
        self.db.execute("INSERT OR REPLACE INTO investigations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        ("run-1", "{}", json.dumps(runtime), "{}", "running", "planning", json.dumps(budget), 1.0, 1.0, None, "[]"))
        self.db.execute("INSERT OR REPLACE INTO model_tasks VALUES (?,?,?,?,?,?,?)",
                        ("task-1", "run-1", 1, "planning", "plan", json.dumps({"input_refs": ["ev-1"]}), "pending"))
        self.db.execute("DELETE FROM discovery_evidence")
        self.db.execute("INSERT INTO discovery_evidence VALUES (?,?,?,?,?,?,?)",
                        ("ev-1", "run-1", "doc-1", "v1", json.dumps({"visibility": "public"}), "public", None))
        self.db.commit()

    def _run(self, run_id):
        row = self.db.execute("SELECT * FROM investigations WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return row

    def close(self):
        self.db.close()


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_JPO_TOKEN", "synthetic-secret-token")
    result = FakeService(tmp_path)
    yield result
    result.close()


def _call(gateway, **overrides):
    args = {"run_id": "run-1", "task_id": "task-1", "task_version": 1,
            "request_id": "req-1", "source": "jpo", "operation": "app_progress",
            "params": {"application_number": "1234567890"}, "input_refs": ["ev-1"]}
    args.update(overrides)
    return gateway.execute(**args)


def _success(request):
    return {"status_code": 200, "headers": {"Content-Type": "application/json"},
            "content": b'{"result":{"statusCode":"100","data":{"case":"1234567890"}}}',
            "url": request["url"]}


def test_injected_success_freezes_raw_body_and_updates_existing_ledger(service, tmp_path):
    sent = []
    gateway = PatentSourceGateway(service, lambda request: (sent.append(request) or _success(request)))
    result = _call(gateway)
    assert result["status"] == "complete"
    assert result["accepted_evidence"] is False
    assert result["coverage"]["normalization"] == "pending"
    assert len(sent) == 1
    artifact = result["raw_response_artifacts"][0]
    assert open(artifact["path"], "rb").read() == _success(sent[0])["content"]
    assert service.db.execute("SELECT status FROM source_queries").fetchone()[0] == "complete"
    assert service.db.execute("SELECT status FROM source_attempts").fetchone()[0] == "received"
    budget = json.loads(service._run("run-1")["budget"])
    assert budget["reserved_source_calls"] == 1
    assert budget["received_source_bytes"] == artifact["size_bytes"]


def test_same_request_id_is_deduplicated_after_reopen(service, tmp_path):
    sent = []
    gateway = PatentSourceGateway(service, lambda request: (sent.append(request) or _success(request)))
    assert _call(gateway)["status"] == "complete"
    service.close()
    reopened = FakeService(tmp_path)
    try:
        result = _call(PatentSourceGateway(reopened, lambda request: sent.append(request)))
        assert result["status"] == "duplicate_request"
        assert len(sent) == 1
    finally:
        reopened.close()


def test_timeout_is_unknown_consumes_budget_and_cannot_be_retried(service):
    sent = []
    def timeout(request):
        sent.append(request)
        raise TimeoutError("synthetic timeout")
    gateway = PatentSourceGateway(service, timeout)
    assert _call(gateway)["status"] == "outcome_unknown"
    assert _call(gateway)["status"] == "duplicate_request"
    assert len(sent) == 1
    assert service.db.execute("SELECT status FROM source_attempts").fetchone()[0] == "outcome_unknown"
    budget = json.loads(service._run("run-1")["budget"])
    assert budget["reserved_source_calls"] == 1
    assert budget["reserved_source_bytes"] == 4096


def test_late_response_does_not_overwrite_unknown_attempt(service):
    def late(request):
        service.db.execute("UPDATE source_attempts SET status='outcome_unknown' WHERE run_id=? AND query_id=?",
                           ("run-1", request["identity"]["query_id"]))
        service.db.commit()
        return _success(request)
    result = _call(PatentSourceGateway(service, late))
    assert result["status"] == "outcome_unknown"
    assert service.db.execute("SELECT status FROM source_attempts").fetchone()[0] == "outcome_unknown"
    assert result["raw_response_artifacts"] == []


@pytest.mark.parametrize("change,expected", [
    ({"task_version": 2}, "stale_task"),
    ({"task_id": "task-other"}, "stale_task"),
    ({"run_id": "run-other"}, "not_found"),
    ({"source": "not_registered"}, "unsupported"),
])
def test_wrong_identity_and_source_are_rejected_without_transport(service, change, expected):
    calls = []
    result = _call(PatentSourceGateway(service, lambda request: calls.append(request)), **change)
    assert result["status"] == expected
    assert calls == []
    assert service.db.execute("SELECT COUNT(*) FROM source_attempts").fetchone()[0] == 0


def test_terminal_run_and_wrong_stage_are_rejected(service):
    calls = []
    service.db.execute("UPDATE investigations SET status='completed' WHERE id='run-1'")
    service.db.commit()
    assert _call(PatentSourceGateway(service, lambda request: calls.append(request)))["status"] == "inactive_run"
    service.db.execute("UPDATE investigations SET status='running',stage='writing' WHERE id='run-1'")
    service.db.commit()
    assert _call(PatentSourceGateway(service, lambda request: calls.append(request)), request_id="req-2")["status"] == "stage_blocked"
    assert calls == []


def test_missing_credential_returns_pending_activation_without_ledger(service, monkeypatch):
    monkeypatch.delenv("TEST_JPO_TOKEN")
    calls = []
    result = _call(PatentSourceGateway(service, lambda request: calls.append(request)))
    assert result["status"] == "pending_activation"
    assert calls == []
    assert service.db.execute("SELECT COUNT(*) FROM source_queries").fetchone()[0] == 0


def test_missing_required_run_budget_is_pending_config_without_dispatch(service):
    runtime = json.loads(service._run("run-1")["runtime"])
    del runtime["budget"]["max_source_response_bytes"]
    service.db.execute("UPDATE investigations SET runtime=? WHERE id='run-1'", (json.dumps(runtime),))
    service.db.commit()
    calls = []
    result = _call(PatentSourceGateway(service, lambda request: calls.append(request)))
    assert result["status"] == "pending_config"
    assert calls == []


def test_missing_reserved_call_counter_is_pending_config(service):
    budget = json.loads(service._run("run-1")["budget"])
    del budget["reserved_source_calls"]
    service.db.execute("UPDATE investigations SET budget=? WHERE id='run-1'", (json.dumps(budget),))
    service.db.commit()
    calls = []
    result = _call(PatentSourceGateway(service, lambda request: calls.append(request)))
    assert result["status"] == "pending_config"
    assert calls == []


def test_budget_exhaustion_is_recorded_without_physical_request(service):
    budget = json.loads(service._run("run-1")["budget"])
    budget["reserved_source_calls"] = budget["max_source_calls"]
    service.db.execute("UPDATE investigations SET budget=? WHERE id='run-1'", (json.dumps(budget),))
    service.db.commit()
    calls = []
    result = _call(PatentSourceGateway(service, lambda request: calls.append(request)))
    assert result["status"] == "budget_denied"
    assert calls == []
    assert service.db.execute("SELECT COUNT(*) FROM source_attempts").fetchone()[0] == 0


def test_per_source_call_cap_is_enforced(service):
    sent = []
    gateway = PatentSourceGateway(service, lambda request: (sent.append(request) or _success(request)))
    assert _call(gateway)["status"] == "complete"
    assert _call(gateway, request_id="req-2")["status"] == "complete"
    assert _call(gateway, request_id="req-3")["status"] == "budget_denied"
    assert len(sent) == 2


def test_oversized_response_is_unknown_and_never_returns_body(service):
    calls = []
    def oversized(request):
        calls.append(request)
        return {"status_code": 200, "headers": {"Content-Type": "application/json"},
                "content": b"x" * (request["max_response_bytes"] + 1), "url": request["url"]}
    result = _call(PatentSourceGateway(service, oversized))
    assert result["status"] == "outcome_unknown"
    assert len(calls) == 1
    assert service.db.execute("SELECT status FROM source_attempts").fetchone()[0] == "outcome_unknown"
    assert result["raw_response_artifacts"] == []


def test_confidential_or_untraceable_input_is_blocked(service):
    service.db.execute("UPDATE discovery_evidence SET visibility='confidential' WHERE evidence_id='ev-1'")
    service.db.commit()
    calls = []
    result = _call(PatentSourceGateway(service, lambda request: calls.append(request)))
    assert result["status"] == "policy_blocked"
    assert calls == []


def test_diagnostic_pending_sources_and_no_profile_are_zero_request(service):
    gateway = PatentSourceGateway(service, lambda request: pytest.fail("diagnose must not dispatch"))
    diagnostic = gateway.diagnose("run-1")
    assert diagnostic["sources"]["tipo_opd"]["status"] == "pending_spec"
    assert diagnostic["sources"]["wipo_pearl"]["status"] == "pending_spec"
    runtime = json.loads(service._run("run-1")["runtime"])
    del runtime["patent_sources"]
    service.db.execute("UPDATE investigations SET runtime=? WHERE id='run-1'", (json.dumps(runtime),))
    service.db.commit()
    assert gateway.diagnose("run-1")["status"] == "pending_config"


def test_secret_is_not_persisted_in_ledger_or_result(service):
    result = _call(PatentSourceGateway(service, _success))
    assert "synthetic-secret-token" not in json.dumps(result)
    assert "synthetic-secret-token" not in service.db.execute("SELECT query FROM source_queries").fetchone()[0]
    assert "synthetic-secret-token" not in service.db.execute("SELECT result FROM source_attempts").fetchone()[0]
    assert "synthetic-secret-token" not in service.db.execute("SELECT payload FROM source_query_details").fetchone()[0]


def test_download_uses_source_and_download_budgets(service, monkeypatch):
    monkeypatch.setenv("TEST_USPTO_KEY", "offline-uspto-key")
    runtime = json.loads(service._run("run-1")["runtime"])
    runtime["patent_sources"]["uspto_odp"] = {
        "enabled": True, "capabilities": ["document_download"], "max_calls": 2,
        "max_response_bytes": 4096, "api_key_env": "TEST_USPTO_KEY",
    }
    service.db.execute("UPDATE investigations SET runtime=? WHERE id='run-1'", (json.dumps(runtime),))
    service.db.commit()
    sent = []
    def download(request):
        sent.append(request)
        return {"status_code": 200, "headers": {"Content-Type": "application/pdf"},
                "content": b"%PDF-1.4 synthetic", "url": request["url"]}
    outcome = _call(PatentSourceGateway(service, download), source="uspto_odp", operation="download_file",
                    request_id="req-download", params={"url": "https://api.uspto.gov/api/v1/download/applications/123/file"})
    assert outcome["status"] == "complete"
    assert len(sent) == 1
    assert "X-API-KEY" in sent[0]["headers"]
    budget = json.loads(service._run("run-1")["budget"])
    assert budget["reserved_download_calls"] == 1
    assert budget["received_download_bytes"] == len(b"%PDF-1.4 synthetic")
    assert budget["received_source_bytes"] == len(b"%PDF-1.4 synthetic")


def test_invalid_timeout_is_rejected(service):
    with pytest.raises(ValueError):
        PatentSourceGateway(service, lambda request: None, timeout_seconds=float("nan"))


def test_profile_schema_requires_explicit_limits_and_env_names_only():
    from pathlib import Path
    schema = json.loads(Path("src/research_harness/schemas/patent-sources.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    valid = {"jpo": {"enabled": False, "capabilities": ["case_progress"], "max_calls": 1,
                      "max_response_bytes": 1024, "token_env": "JPO_TOKEN"}}
    assert not list(validator.iter_errors(valid))
    invalid = {"jpo": {**valid["jpo"], "token_env": "secret-value"}}
    assert list(validator.iter_errors(invalid))
    assert list(validator.iter_errors({"jpo": {"enabled": True, "capabilities": ["case_progress"]}}))


def test_source_diagnostic_cli_never_dispatches(tmp_path, capsys):
    from research_harness.cli import main
    status = main(["patent-source-diagnose", "--workspace", str(tmp_path), "--run-id", "missing"])
    assert status == 4
    assert json.loads(capsys.readouterr().out)["status"] == "not_found"


def test_patent_analyze_cli_accepts_local_bundle_and_reports_review_boundary(tmp_path, capsys):
    from research_harness.cli import main
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps({"schema_version":"1", "run_id":"run-frozen", "input_id":"input-1",
                                "selection_reason":"fixture selection", "publications":[{"publication_id":"P1"}]}), encoding="utf-8")
    status = main(["patent-analyze", "--input", str(path.resolve())])
    output = json.loads(capsys.readouterr().out)
    assert status == 4
    assert output["input_binding"]["path"] == str(path.resolve())
    assert output["claim_acceptance"] == "not_assessed"


def test_stopped_between_preflight_and_logical_lease_never_reserves_or_dispatches(service, monkeypatch):
    gateway = PatentSourceGateway(service, lambda request: pytest.fail("stopped run must not dispatch"))
    original = gateway._begin_logical_request
    def stop_then_begin(*args, **kwargs):
        service.db.execute("UPDATE investigations SET status='stopped' WHERE id='run-1'")
        service.db.commit()
        return original(*args, **kwargs)
    monkeypatch.setattr(gateway, "_begin_logical_request", stop_then_begin)
    result = _call(gateway)
    assert result["status"] == "inactive_run"
    assert service.db.execute("SELECT COUNT(*) FROM source_queries").fetchone()[0] == 0
    assert service.db.execute("SELECT COUNT(*) FROM source_attempts").fetchone()[0] == 0
    assert json.loads(service._run("run-1")["budget"])["reserved_source_calls"] == 0


def test_completed_between_preflight_and_logical_lease_is_stale_without_reservation(service, monkeypatch):
    gateway = PatentSourceGateway(service, lambda request: pytest.fail("stale task must not dispatch"))
    original = gateway._begin_logical_request
    def complete_then_begin(*args, **kwargs):
        service.db.execute("UPDATE model_tasks SET status='completed' WHERE id='task-1'")
        service.db.commit()
        return original(*args, **kwargs)
    monkeypatch.setattr(gateway, "_begin_logical_request", complete_then_begin)
    result = _call(gateway)
    assert result["status"] == "stale_task"
    assert service.db.execute("SELECT COUNT(*) FROM source_attempts").fetchone()[0] == 0
    assert json.loads(service._run("run-1")["budget"])["reserved_source_calls"] == 0


def test_logical_lease_serializes_different_requests(service):
    nested = []
    gateway = None
    def transport(request):
        nested.append(_call(gateway, request_id="req-concurrent"))
        return _success(request)
    gateway = PatentSourceGateway(service, transport)
    assert _call(gateway)["status"] == "complete"
    assert nested[0]["status"] == "busy"
    assert service.db.execute("SELECT COUNT(*) FROM source_attempts").fetchone()[0] == 1


def test_prepared_receipts_fingerprint_actual_requests_without_credentials(service):
    gateway = PatentSourceGateway(service, _success)
    assert _call(gateway, request_id="receipt-1", params={"application_number": "1111111111"})["status"] == "complete"
    assert _call(gateway, request_id="receipt-2", params={"application_number": "2222222222"})["status"] == "complete"
    rows = list(service.db.execute("SELECT result FROM source_attempts ORDER BY query_id"))
    receipts = [json.loads(row[0]) for row in rows]
    assert all(item.get("request_sha256") and item.get("request_receipt", {}).get("url")
               and item.get("request_receipt_status") == "recorded_before_dispatch" for item in receipts)
    assert receipts[0]["request_sha256"] != receipts[1]["request_sha256"]
    assert "synthetic-secret-token" not in json.dumps(receipts)


@pytest.mark.parametrize("runtime_change,expected", [
    ({"data_mode": "synthetic"}, "pending_activation"),
    ({"allow_network": False}, "pending_activation"),
    ({"data_policy": {"allow_query_egress": False}}, "pending_activation"),
])
def test_diagnose_never_enables_dispatch_when_runtime_policy_blocks_it(service, runtime_change, expected):
    runtime = json.loads(service._run("run-1")["runtime"])
    runtime.update(runtime_change)
    service.db.execute("UPDATE investigations SET runtime=? WHERE id='run-1'", (json.dumps(runtime),))
    service.db.commit()
    jpo = PatentSourceGateway(service, lambda request: pytest.fail("diagnose must not dispatch")).diagnose("run-1")["sources"]["jpo"]
    assert jpo["status"] == expected
    assert jpo["dispatch_enabled"] is False


def test_invalid_credential_environment_name_is_pending_config(service):
    runtime = json.loads(service._run("run-1")["runtime"])
    runtime["patent_sources"]["jpo"]["token_env"] = "BAD ENV"
    service.db.execute("UPDATE investigations SET runtime=? WHERE id='run-1'", (json.dumps(runtime),))
    service.db.commit()
    gateway = PatentSourceGateway(service, lambda request: pytest.fail("invalid env name must not dispatch"))
    assert gateway.diagnose("run-1")["sources"]["jpo"]["status"] == "pending_config"
    assert _call(gateway)["status"] == "pending_config"


@pytest.mark.parametrize("lease_status", ["reserved", "dispatching", "outcome_unknown"])
def test_real_core_engine_lease_states_block_source_dispatch(service, lease_status):
    service.db.execute("INSERT INTO engine_task_leases VALUES (?,?,?,?,?)",
                       (f"lease-{lease_status}", "run-1", "task-1", 1, lease_status))
    service.db.commit()
    sent = []
    result = _call(PatentSourceGateway(service, lambda request: sent.append(request)))
    assert result["status"] == "busy"
    assert sent == []
    assert service.db.execute("SELECT COUNT(*) FROM source_queries").fetchone()[0] == 0
    assert json.loads(service._run("run-1")["budget"])["reserved_source_calls"] == 0


def test_accepted_engine_lease_blocks_only_its_task_version(service):
    service.db.execute("INSERT INTO model_tasks VALUES (?,?,?,?,?,?,?)",
                       ("old-task", "run-1", 1, "planning", "plan", json.dumps({"input_refs": ["ev-1"]}), "completed"))
    service.db.execute("INSERT INTO engine_task_leases VALUES (?,?,?,?,?)",
                       ("lease-old", "run-1", "old-task", 1, "accepted"))
    service.db.commit()
    sent = []
    result = _call(PatentSourceGateway(service, lambda request: (sent.append(request) or _success(request))))
    assert result["status"] == "complete"
    assert len(sent) == 1
    assert service.db.execute("SELECT COUNT(*) FROM source_attempts").fetchone()[0] == 1


def test_accepted_engine_lease_blocks_current_task_version(service):
    service.db.execute("INSERT INTO engine_task_leases VALUES (?,?,?,?,?)",
                       ("lease-current", "run-1", "task-1", 1, "accepted"))
    service.db.commit()
    sent = []
    result = _call(PatentSourceGateway(service, lambda request: sent.append(request)))
    assert result["status"] == "busy"
    assert sent == []
    assert service.db.execute("SELECT COUNT(*) FROM source_queries").fetchone()[0] == 0


def test_missing_model_call_ledger_fails_closed(service):
    service.db.execute("DROP TABLE model_api_calls")
    service.db.commit()
    sent = []
    result = _call(PatentSourceGateway(service, lambda request: sent.append(request)))
    assert result["status"] == "pending_config"
    assert sent == []
    assert service.db.execute("SELECT COUNT(*) FROM source_queries").fetchone()[0] == 0
    assert json.loads(service._run("run-1")["budget"])["reserved_source_calls"] == 0
