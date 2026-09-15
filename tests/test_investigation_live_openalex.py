import json

import pytest

from research_harness import investigation
from research_harness.investigation import InvestigationService
from research_harness.investigation_sources import SourceError


def _runtime():
    return {"mode": "host", "data_mode": "live", "allow_network": True,
            "budget": {"max_tasks": 8, "max_source_calls": 4, "max_pages_per_query": 2,
                       "max_downloads": 1, "max_download_calls": 2, "max_download_bytes": 1024},
            "sources": {"openalex": {"anonymous": True, "year_min": 2020,
                                         "sort": "relevance_score:desc", "page_size": 5,
                                         "max_candidates": 10, "max_pages": 2, "timeout_seconds": 30}}}


def _spec():
    return {"status": "ready", "project_id": "live-test", "revision": 1,
            "research_question": "q", "report_targets": ["technical_report"], "references": []}


def test_live_page_retries_once_and_persists_actual_page(monkeypatch, tmp_path):
    calls = []
    class FakeTransport:
        def __init__(self, runtime, on_attempt): self.on_attempt = on_attempt
        def search(self, source, query, cursor=None):
            self.on_attempt({"attempt": 1}); calls.append(cursor)
            if len(calls) == 1: raise SourceError("RH_SOURCE_TIMEOUT", "timeout")
            return {"candidates": [{"document_id": "W1", "source": "openalex", "title": "title"}], "next_cursor": None, "complete": True}
    monkeypatch.setattr(investigation, "OpenAlexTransport", FakeTransport)
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(_spec(), _runtime(), {"reference_evidence": [{"evidence_id": "b1", "document_id": "base", "version_id": "v1", "text": "base", "locator": {"kind": "page", "value": "1"}}]})["run_id"]
        result = service._search_live_pages(run, "q1", "query", _runtime())
        assert result[1] == "complete" and len(calls) == 2
        rows = list(service.db.execute("SELECT status,result FROM source_attempts WHERE run_id=? ORDER BY attempt", (run,)))
        assert [row["status"] for row in rows] == ["RH_SOURCE_TIMEOUT", "success"]
        assert json.loads(rows[-1]["result"])["candidates"][0]["document_id"] == "W1"


def test_live_successful_page_is_reused_without_network(monkeypatch, tmp_path):
    calls = []
    class FakeTransport:
        def __init__(self, runtime, on_attempt): self.on_attempt = on_attempt
        def search(self, source, query, cursor=None):
            calls.append(cursor); self.on_attempt({"attempt": 1})
            return {"candidates": [{"document_id": "W1", "source": "openalex", "title": "title"}], "next_cursor": None, "complete": True}
    monkeypatch.setattr(investigation, "OpenAlexTransport", FakeTransport)
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(_spec(), _runtime(), {"reference_evidence": [{"evidence_id": "b1", "document_id": "base", "version_id": "v1", "text": "base", "locator": {"kind": "page", "value": "1"}}]})["run_id"]
        assert service._search_live_pages(run, "q1", "query", _runtime())[1] == "complete"
        assert service._search_live_pages(run, "q1", "query", _runtime())[1] == "complete"
        assert calls == [None]


def test_live_rejects_fixture_and_requires_explicit_network(tmp_path):
    with InvestigationService(tmp_path) as service:
        with pytest.raises(Exception, match="network opt-in"):
            service.create_investigation(_spec(), {**_runtime(), "allow_network": False}, {"reference_evidence": []})
        with pytest.raises(Exception, match="synthetic source fixtures"):
            service.create_investigation(_spec(), _runtime(), {"reference_evidence": [], "sources": [{"document_id": "fixture"}]})


def test_live_confidential_reference_evidence_is_policy_gated(tmp_path):
    evidence = {"evidence_id": "secret", "document_id": "base", "version_id": "v1", "text": "secret", "locator": {"kind": "page", "value": "1"}, "visibility": "confidential", "company_id": "other"}
    with InvestigationService(tmp_path) as service:
        started = service.create_investigation(_spec(), _runtime(), {"reference_evidence": [evidence]})
        assert started["status"] == "policy_blocked"


def test_live_pending_page_is_not_resent(monkeypatch, tmp_path):
    calls = []
    class FakeTransport:
        def __init__(self, runtime, on_attempt): pass
        def search(self, *args): calls.append(args); raise AssertionError("must not send")
    monkeypatch.setattr(investigation, "OpenAlexTransport", FakeTransport)
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(_spec(), _runtime(), {"reference_evidence": []})["run_id"]
        service.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)", (run, "q1", None, 1, "pending", "{}")); service.db.commit()
        result = service._search_live_pages(run, "q1", "query", _runtime())
        assert result[1:] == ("partial", "uncertain prior source call") and not calls


def test_live_http_budget_counts_failed_attempts(monkeypatch, tmp_path):
    calls = []
    class FakeTransport:
        def __init__(self, runtime, on_attempt): self.on_attempt = on_attempt
        def search(self, *args): calls.append(args); self.on_attempt({"attempt": 1}); raise SourceError("RH_SOURCE_TIMEOUT", "timeout")
    runtime = _runtime(); runtime["budget"]["max_source_calls"] = 1
    monkeypatch.setattr(investigation, "OpenAlexTransport", FakeTransport)
    with InvestigationService(tmp_path) as service:
        run = service.create_investigation(_spec(), runtime, {"reference_evidence": []})["run_id"]
        result = service._search_live_pages(run, "q1", "query", runtime)
        assert result == ([], "partial", "RH_SOURCE_BUDGET")
        assert len(calls) == 2
        assert service.status(run)["budget"]["reserved_source_calls"] == 1


def test_live_collector_retries_rate_limited_http_then_persists_page(monkeypatch, tmp_path):
    class Response:
        def __init__(self, status_code, payload=None, headers=None): self.status_code=status_code; self.payload=payload; self.headers=headers or {}
        def json(self): return self.payload
        def close(self): pass
    class Session:
        def __init__(self): self.responses=[Response(429, headers={"Retry-After": "2"}), Response(200, {"results": [{"id": "https://openalex.org/W1", "title": "paper", "doi": "https://doi.org/10.1/x", "publication_year": 2024, "type": "article", "authorships": [], "locations": [], "abstract_inverted_index": {}}], "meta": {"next_cursor": None}})]
        def get(self, *args, **kwargs): return self.responses.pop(0)
    import research_harness.investigation_sources as sources
    sleeps=[]
    monkeypatch.setattr(sources.literature.requests, "Session", Session)
    monkeypatch.setattr(investigation.time, "sleep", sleeps.append)
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(_spec(), _runtime(), {"reference_evidence": []})["run_id"]
        assert service._search_live_pages(run, "q1", "query", _runtime())[1] == "complete"
        assert sleeps == [2.0]
        rows=list(service.db.execute("SELECT status,result FROM source_attempts WHERE run_id=? ORDER BY attempt",(run,)))
        assert [row["status"] for row in rows] == ["RH_SOURCE_SOURCE_UNAVAILABLE", "success"]
        assert json.loads(rows[-1]["result"])["candidates"][0]["doi"] == "10.1/x"


def test_confidential_reference_evidence_blocks_query_egress(tmp_path):
    runtime=_runtime(); runtime["data_policy"]={"company_id":"co","allowed_models":["local"],"allow_query_egress":False}; runtime["model_id"]="local"
    evidence={"evidence_id":"secret","document_id":"base","version_id":"v1","text":"secret","locator":{"kind":"page","value":"1"},"visibility":"confidential","company_id":"co"}
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(_spec(),runtime,{"reference_evidence":[evidence]})["run_id"]
        assert service._query_is_sensitive({"input_refs":["secret"]},service._run(run))


def test_synthetic_confidential_baseline_is_sensitive_without_input_refs(tmp_path):
    runtime={"mode":"host","data_mode":"synthetic","model_id":"local","data_policy":{"company_id":"co","allowed_models":["local"],"allow_query_egress":False},"budget":{"max_tasks":8}}
    scenario={"references":[{"document_id":"secret","version":"v1","text":"secret","visibility":"confidential","company_id":"co"}],"sources":[]}
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(_spec(),runtime,scenario)["run_id"]
        assert service._query_is_sensitive({"input_refs":[]},service._run(run))
