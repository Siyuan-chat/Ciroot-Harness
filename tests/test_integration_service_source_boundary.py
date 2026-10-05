import json

import pytest

from research_harness.cli import main as cli_main
from research_harness.errors import ValidationError
from research_harness.investigation import InvestigationError, InvestigationService
from research_harness.investigation_sources import SourceError
from research_harness import investigation


def _runtime():
    return {
        "mode": "host", "data_mode": "live", "allow_network": True,
        "data_policy": {"allow_query_egress": True},
        "sources": {"openalex": {"anonymous": True, "year_min": 2020, "page_size": 5},
            "epo": {"page_size": 1, "max_pages": 1, "max_candidates": 1}},
        "patent_sources": {"jpo": {"enabled": True, "token_env": "RH_TEST_JPO_TOKEN",
            "capabilities": ["case_progress"], "max_calls": 2, "max_response_bytes": 2048}},
        "budget": {"max_tasks": 8, "max_source_calls": 2, "max_source_bytes": 4096,
            "max_source_response_bytes": 2048, "max_pages_per_query": 1},
    }


def _spec():
    return {"status": "ready", "project_id": "service-source-test", "revision": 1,
        "research_question": "synthetic contract test", "report_targets": ["technical_report"], "references": []}


def _reference():
    return {"evidence_id": "public-ref-1", "document_id": "public-doc-1", "version_id": "v1",
        "text": "public frozen reference", "locator": {"kind": "page", "value": "1"}, "visibility": "public"}


def _create(service):
    run_id = service.create_investigation(_spec(), _runtime(), {"reference_evidence": [_reference()]})["run_id"]
    task = next(item for item in service.get_pending_tasks(run_id) if item["role"] == "planning")
    return run_id, task


def test_actual_service_executes_injected_source_and_cli_pending_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RH_TEST_JPO_TOKEN", "synthetic-token-value")
    sent = []
    def transport(request):
        sent.append(request)
        return {"status_code": 200, "headers": {"Content-Type": "application/json"},
            "content": b'{"result":{"statusCode":"100","data":{"case":"1234567890"}}}',
            "url": request["url"]}
    workspace = tmp_path / "service"
    with InvestigationService(workspace, source_request_callback=transport) as service:
        run_id, task = _create(service)
        assert "execute_patent_source" in task["allowed_operations"]
        result = service.execute_patent_source(run_id, task["task_id"], task["task_version"], "offline-call-1",
            "jpo", "app_progress", {"application_number": "1234567890"}, input_refs=task["input_refs"])
        assert result["status"] == "complete"
        assert result["accepted_evidence"] is False
        assert len(sent) == 1
        attempt = service.db.execute("SELECT status,result FROM source_attempts WHERE run_id=? AND query_id LIKE 'patent:%'", (run_id,)).fetchone()
        assert attempt["status"] == "received"
        assert json.loads(attempt["result"])["request_receipt_status"] == "recorded_before_dispatch"
        assert service.status(run_id)["budget"]["reserved_source_calls"] == 1
    # The command path is exercised with missing credentials so the built-in
    # transport returns pending_activation without opening a network request.
    monkeypatch.delenv("RH_TEST_JPO_TOKEN")
    with InvestigationService(workspace) as service:
        run_id, task = _create(service)
    params_file=tmp_path/"source-params.json"; refs_file=tmp_path/"source-input-refs.json"
    params_file.write_text('{"application_number":"1234567890"}',encoding="utf-8")
    refs_file.write_text(json.dumps(task["input_refs"]),encoding="utf-8")
    code = cli_main(["patent-source-execute", "--workspace", str(workspace), "--run-id", run_id,
        "--task-id", task["task_id"], "--task-version", str(task["task_version"]), "--request-id", "cli-offline-1",
        "--source", "jpo", "--operation", "app_progress", "--params-file", str(params_file),
        "--input-refs-file", str(refs_file)])
    output = json.loads(capsys.readouterr().out)
    assert code == 4 and output["status"] == "pending_activation"


def test_cli_rejects_nonabsolute_input_and_does_not_echo_file_secrets(tmp_path, capsys, monkeypatch):
    code=cli_main(["patent-source-execute","--workspace",str(tmp_path),"--run-id","run","--task-id","task",
        "--task-version","1","--request-id","cli","--source","jpo","--operation","app_progress",
        "--params-file","relative.json","--input-refs-json","[]"])
    assert code==2
    assert "absolute local path" in capsys.readouterr().err
    monkeypatch.setenv("RH_TEST_JPO_TOKEN","synthetic-token-value")
    secret="SYNTHETIC-SECRET-DO-NOT-PRINT"
    workspace=tmp_path/"cli-secret"
    with InvestigationService(workspace) as service:
        run,task=_create(service)
    params_file=tmp_path/"secret-params.json";refs_file=tmp_path/"refs.json"
    params_file.write_text(json.dumps({"application_number":"1234567890","api_key":secret}),encoding="utf-8")
    refs_file.write_text(json.dumps(task["input_refs"]),encoding="utf-8")
    code=cli_main(["patent-source-execute","--workspace",str(workspace),"--run-id",run,"--task-id",task["task_id"],
        "--task-version",str(task["task_version"]),"--request-id","cli-secret-1","--source","jpo","--operation","app_progress",
        "--params-file",str(params_file),"--input-refs-file",str(refs_file)])
    output=capsys.readouterr().out
    assert code==4 and secret not in output


@pytest.mark.parametrize("contents", [None, bytes((255, 254)), b'{"api_key":"SECRET-CONTENT-NEVER-ECHOED",'])
def test_cli_file_read_errors_are_structured_and_redacted(tmp_path, capsys, contents):
    params=tmp_path/"bad-params.json"
    path=params
    if contents is None:
        pass
    else:
        path.write_bytes(contents)
    code=cli_main(["patent-source-execute","--workspace",str(tmp_path),"--run-id","run","--task-id","task",
        "--task-version","1","--request-id","bad-input","--source","jpo","--operation","app_progress",
        "--params-file",str(path),"--input-refs-json","[]"])
    captured=capsys.readouterr()
    assert code==2
    assert "RH_PATENT_INPUT" in captured.err
    assert "Traceback" not in captured.err
    assert "SECRET-CONTENT-NEVER-ECHOED" not in captured.err


def test_cli_rejects_network_input_path(tmp_path, capsys):
    code=cli_main(["patent-source-execute","--workspace",str(tmp_path),"--run-id","run","--task-id","task",
        "--task-version","1","--request-id","network-path","--source","jpo","--operation","app_progress",
        "--params-file","//server/share/params.json","--input-refs-json","[]"])
    captured=capsys.readouterr()
    assert code==2 and "absolute local path" in captured.err
    assert "Traceback" not in captured.err


def test_source_logical_lease_blocks_submit_model_and_engine_without_attempt(tmp_path):
    with InvestigationService(tmp_path) as service:
        run_id, task = _create(service)
        # The logical row is the reservation. There is intentionally no
        # physical attempt yet; downstream writers must still remain blocked.
        query_id = "patent:dispatching-without-attempt"
        service.db.execute("INSERT INTO source_queries VALUES (?,?,?,?,?,?,?,?)",
            (run_id, query_id, "jpo", "{}", None, json.dumps(task["input_refs"]), "dispatching", None))
        service.db.commit()
        with pytest.raises(InvestigationError, match="source request is unresolved"):
            service.submit_model_result(run_id, task["task_id"], {"search_plan": {"queries": []}}, task["task_version"])
        with pytest.raises(InvestigationError, match="source request is unresolved"):
            service.reserve_model_call(run_id, task["task_id"], task["task_version"])
        with pytest.raises(InvestigationError, match="source request is unresolved"):
            service.reserve_engine_lease(run_id, task["task_id"], task["task_version"])
        assert service.get_pending_tasks(run_id) == []


def test_service_stop_wins_before_source_logical_lease(tmp_path,monkeypatch):
    from research_harness.patent_source_gateway import PatentSourceGateway
    monkeypatch.setenv("RH_TEST_JPO_TOKEN","synthetic-token-value")
    sent=[]
    with InvestigationService(tmp_path,source_request_callback=lambda req:sent.append(req)) as service:
        run,task=_create(service)
        original=PatentSourceGateway._begin_logical_request
        def stop_before_begin(gateway,*args,**kwargs):
            gateway.service.db.execute("UPDATE investigations SET status='stopped' WHERE id=?",(args[0],));gateway.service.db.commit()
            return original(gateway,*args,**kwargs)
        monkeypatch.setattr(PatentSourceGateway,"_begin_logical_request",stop_before_begin)
        result=service.execute_patent_source(run,task["task_id"],task["task_version"],"stop-race-1","jpo","app_progress",
            {"application_number":"1234567890"},input_refs=task["input_refs"])
        budget=service.status(run)["budget"]
        assert result["status"]=="inactive_run" and sent==[]
        assert budget["reserved_source_calls"]==0
        assert service.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=?",(run,)).fetchone()[0]==0
        assert service.db.execute("SELECT COUNT(*) FROM source_queries WHERE run_id=?",(run,)).fetchone()[0]==0


def test_service_source_execution_rejects_cross_scope_refs_and_exhausted_budget(tmp_path,monkeypatch):
    monkeypatch.setenv("RH_TEST_JPO_TOKEN","synthetic-token-value")
    sent=[]
    def transport(request):sent.append(request);return {"status_code":200,"headers":{},"content":b'{"result":{"statusCode":"100","data":{}}}'}
    with InvestigationService(tmp_path,source_request_callback=transport) as service:
        run,task=_create(service)
        result=service.execute_patent_source(run,task["task_id"],task["task_version"],"wrong-ref-1","jpo","app_progress",
            {"application_number":"1234567890"},input_refs=["unrelated-library:private-id"])
        assert result["status"]=="policy_blocked" and not sent
        assert service.db.execute("SELECT COUNT(*) FROM source_queries WHERE run_id=?",(run,)).fetchone()[0]==0
        budget=json.loads(service._run(run)["budget"]);budget["max_source_calls"]=budget["reserved_source_calls"]
        stored=service._run(run);runtime=json.loads(stored["runtime"]);runtime["budget"]["max_source_calls"]=budget["max_source_calls"]
        service.db.execute("UPDATE investigations SET budget=?,runtime=? WHERE id=?",(json.dumps(budget),json.dumps(runtime),run));service.db.commit()
        result=service.execute_patent_source(run,task["task_id"],task["task_version"],"budget-1","jpo","app_progress",
            {"application_number":"1234567890"},input_refs=task["input_refs"])
        assert result["status"]=="budget_denied" and not sent


def test_service_source_execution_honors_query_egress_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("RH_TEST_JPO_TOKEN", "synthetic-token-value")
    sent = []
    with InvestigationService(tmp_path, source_request_callback=lambda request: sent.append(request)) as service:
        run_id, task = _create(service)
        stored = service._run(run_id)
        runtime = json.loads(stored["runtime"])
        runtime["data_policy"]["allow_query_egress"] = False
        service.db.execute("UPDATE investigations SET runtime=? WHERE id=?", (json.dumps(runtime), run_id))
        service.db.commit()
        result = service.execute_patent_source(run_id, task["task_id"], task["task_version"], "policy-deny-1",
            "jpo", "app_progress", {"application_number": "1234567890"}, input_refs=task["input_refs"])
        assert result["status"] == "policy_blocked"
        assert sent == []
        assert service.db.execute("SELECT COUNT(*) FROM source_queries WHERE run_id=?", (run_id,)).fetchone()[0] == 0


def test_live_legacy_queries_require_frozen_same_source_references(tmp_path):
    with InvestigationService(tmp_path) as service:
        run,_=_create(service);row=service._run(run);runtime=json.loads(row["runtime"]);scenario=json.loads(row["scenario"])
        no_ref=[{"query_id":"q1","source":"openalex","query":"membrane","input_refs":[],"parent_query_id":None}]
        with pytest.raises(InvestigationError,match="explicit frozen input references"):
            service._validate_queries(no_ref,set(),{"public-ref-1"},runtime,scenario)
        cross_source=[
            {"query_id":"q1","source":"openalex","query":"membrane","input_refs":["query:q2"],"parent_query_id":None},
            {"query_id":"q2","source":"epo","query":"ta=membrane","input_refs":["public-ref-1"],"parent_query_id":None},
        ]
        with pytest.raises(InvestigationError,match="same source"):
            service._validate_queries(cross_source,set(),{"public-ref-1"},runtime,scenario)


def test_actual_service_unknown_source_result_is_not_resent_after_reopen(tmp_path,monkeypatch):
    monkeypatch.setenv("RH_TEST_JPO_TOKEN","synthetic-token-value")
    sends=[]
    def timeout(request):sends.append(request);raise TimeoutError("synthetic network timeout")
    workspace=tmp_path/"unknown-source"
    with InvestigationService(workspace,source_request_callback=timeout) as service:
        run,task=_create(service)
        first=service.execute_patent_source(run,task["task_id"],task["task_version"],"unknown-call-1","jpo","app_progress",
            {"application_number":"1234567890"},input_refs=task["input_refs"])
        assert first["status"]=="outcome_unknown"
    with InvestigationService(workspace,source_request_callback=timeout) as reopened:
        second=reopened.execute_patent_source(run,task["task_id"],task["task_version"],"unknown-call-1","jpo","app_progress",
            {"application_number":"1234567890"},input_refs=task["input_refs"])
        assert second["status"]=="duplicate_request"
        assert reopened.status(run)["budget"]["reserved_source_calls"]==1
    assert len(sends)==1


def test_actual_service_model_engine_source_mutex_shares_transactions(tmp_path,monkeypatch):
    monkeypatch.setenv("RH_TEST_JPO_TOKEN","synthetic-token-value")
    with InvestigationService(tmp_path) as service:
        run,task=_create(service)
        row=service._run(run);runtime=json.loads(row["runtime"]);runtime["mode"]="api";runtime["budget"]["max_model_calls"]=3
        budget=json.loads(row["budget"]);budget["max_model_calls"]=3
        service.db.execute("UPDATE investigations SET runtime=?,budget=? WHERE id=?",(json.dumps(runtime),json.dumps(budget),run));service.db.commit()
        model_call=service.reserve_model_call(run,task["task_id"],task["task_version"])
        assert service.execute_patent_source(run,task["task_id"],task["task_version"],"model-busy-1","jpo","app_progress",
            {"application_number":"1234567890"},input_refs=task["input_refs"])["status"]=="busy"
        with pytest.raises(InvestigationError,match="model request is unresolved"):
            service.reserve_engine_lease(run,task["task_id"],task["task_version"])
        service.db.execute("UPDATE model_api_calls SET status='failed' WHERE id=?",(model_call,));service.db.commit()
        lease=service.reserve_engine_lease(run,task["task_id"],task["task_version"])
        assert service.execute_patent_source(run,task["task_id"],task["task_version"],"engine-busy-1","jpo","app_progress",
            {"application_number":"1234567890"},input_refs=task["input_refs"])["status"]=="busy"
        with pytest.raises(InvestigationError,match="engine request is unresolved"):
            service.reserve_model_call(run,task["task_id"],task["task_version"])
        assert lease


@pytest.mark.parametrize("kind", ["section_kind", "block_kind"])
def test_real_writing_task_accepts_only_report_block_kinds(tmp_path, kind):
    with InvestigationService(tmp_path) as service:
        run_id, _ = _create(service)
        service._task(run_id, "writing", "write", {"input_refs": ["task:synthesis"]})
        task = next(item for item in service.get_pending_tasks(run_id) if item["role"] == "writing")
        section = {"deliverable_type": "technical_report", "language": "en", "section_id": "s1",
            "title": "Methods", "body": "Synthetic text", "claim_ids": []}
        valid = {"sections": [{**section, kind: "method"}]}
        assert service.submit_model_result(run_id, task["task_id"], valid, task["task_version"])["status"] == "accepted"
    with InvestigationService(tmp_path / ("negative-" + kind)) as service:
        run_id, _ = _create(service)
        service._task(run_id, "writing", "write", {"input_refs": ["task:synthesis"]})
        task = next(item for item in service.get_pending_tasks(run_id) if item["role"] == "writing")
        invalid = {"sections": [{**section, kind: "gap"}]}
        with pytest.raises(InvestigationError, match="schema validation"):
            service.submit_model_result(run_id, task["task_id"], invalid, task["task_version"])


def test_enabled_source_requires_explicit_byte_limits(tmp_path):
    runtime = _runtime()
    del runtime["budget"]["max_source_bytes"]
    with pytest.raises(ValidationError, match="explicit positive source byte"):
        with InvestigationService(tmp_path) as service:
            service.create_investigation(_spec(), runtime, {"reference_evidence": [_reference()]})


def _epo_runtime():
    return {"mode":"host","data_mode":"live","allow_network":True,
        "sources":{"epo":{"page_size":1,"max_pages":1,"max_candidates":1}},
        "budget":{"max_tasks":8,"max_source_calls":4,"max_source_bytes":65536,
            "max_source_response_bytes":16384,"max_pages_per_query":1}}


def test_epo_timeout_receipt_is_unknown_and_survives_service_reopen(tmp_path,monkeypatch):
    calls=[]
    def timeout(*args,**kwargs):calls.append((args,kwargs));raise investigation.requests.Timeout("synthetic")
    monkeypatch.setattr(investigation.requests,"request",timeout)
    workspace=tmp_path/"epo-unknown"
    with InvestigationService(workspace) as service:
        run=service.create_investigation(_spec(),_epo_runtime(),{"reference_evidence":[]})["run_id"]
        with pytest.raises(SourceError,match="outcome is unknown"):
            service._epo_request(run,"search","GET","https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc/US123A1/biblio",params={"q":"ta=membrane"})
        row=service.db.execute("SELECT status,result FROM source_attempts WHERE run_id=? AND query_id='epo-http'",(run,)).fetchone()
        assert row["status"]=="outcome_unknown"
        assert json.loads(row["result"])["request_receipt_status"]=="recorded"
        assert service.status(run)["budget"]["reserved_source_calls"]==1
        assert service.status(run)["budget"]["reserved_source_bytes"]==_epo_runtime()["budget"]["max_source_response_bytes"]
    with InvestigationService(workspace) as reopened:
        with pytest.raises(SourceError,match="uncertain"):
            reopened._epo_request(run,"search","GET","https://ops.epo.org/3.2/rest-services/published-data/publication/epodoc/US123A1/biblio",params={"q":"ta=membrane"})
    assert len(calls)==1


def test_epo_auth_secrets_never_enter_ledger_or_frozen_files(tmp_path,monkeypatch):
    secret="SYNTHETIC-ACCESS-TOKEN-DO-NOT-STORE"
    monkeypatch.setenv("EPO_CONSUMER_KEY","SYNTHETIC-CLIENT-KEY")
    monkeypatch.setenv("EPO_CONSUMER_SECRET","SYNTHETIC-CLIENT-SECRET")
    calls=[]
    class Response:
        status_code=200
        def __init__(self,body):self.body=body
        def __enter__(self):return self
        def __exit__(self,*_):return None
        def iter_content(self,size):yield self.body
    def synthetic_request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        body=json.dumps({"access_token":secret,"expires_in":3600}).encode() if url.endswith("/auth/accesstoken") else b"<synthetic-response/>"
        return Response(body)
    monkeypatch.setattr(investigation.requests,"request",synthetic_request)
    workspace=tmp_path/"epo-auth"
    with InvestigationService(workspace) as service:
        run=service.create_investigation(_spec(),_epo_runtime(),{"reference_evidence":[]})["run_id"]
        client=service._epo_client(run)
        client.authenticate()
        client.get("search","/3.2/rest-services/published-data/publication/epodoc/US123A1/biblio",params={"q":"ta=membrane"})
        assert any(kwargs.get("auth")==("SYNTHETIC-CLIENT-KEY","SYNTHETIC-CLIENT-SECRET") for _,_,kwargs in calls)
        assert any(kwargs.get("headers",{}).get("Authorization")=="Bearer "+secret for _,_,kwargs in calls)
        dumped=" ".join(row[0] for row in service.db.execute("SELECT result FROM source_attempts WHERE run_id=?",(run,)))
        assert secret not in dumped and "SYNTHETIC-CLIENT-SECRET" not in dumped
    persisted=" ".join(p.read_bytes().decode("utf-8",errors="ignore") for p in workspace.rglob("*") if p.is_file())
    assert secret not in persisted and "SYNTHETIC-CLIENT-SECRET" not in persisted and "SYNTHETIC-CLIENT-KEY" not in persisted
