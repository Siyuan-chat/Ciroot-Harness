"""Offline protocol checks for the evidence-led, two-source query loop."""

import hashlib
import json
import sys
from types import ModuleType
from types import SimpleNamespace

import pytest

from research_harness import investigation
from research_harness import literature
from research_harness import rag
from research_harness.investigation import InvestigationError, InvestigationService
from research_harness.investigation_sources import SourceError
from research_harness.rag import RagLibrary


class _Vector(list):
    def tolist(self):
        return list(self)


class _Embedder:
    def embed(self, texts, **_kwargs):
        return iter(_Vector([1.0]) for _ in texts)


class _Index:
    def collection_exists(self, _name):
        return True

    def query_points(self, *_args, **_kwargs):
        return SimpleNamespace(points=[])


class _Splitter:
    def __init__(self, **_kwargs):
        pass

    def split_text(self, text):
        return [text]


def _reference_library(tmp_path, monkeypatch):
    """Exercise actual TXT import and hybrid RagLibrary search without model downloads."""
    qdrant = ModuleType("qdrant_client")
    qdrant.models = SimpleNamespace(
        Filter=lambda **kw: kw, FieldCondition=lambda **kw: kw, MatchAny=lambda **kw: kw,
    )
    bm25 = ModuleType("rank_bm25")

    class _BM25:
        def __init__(self, corpus):
            self.corpus = corpus

        def get_scores(self, query):
            words = set(query)
            return [float(len(words.intersection(document))) for document in self.corpus]

    bm25.BM25Okapi = _BM25
    monkeypatch.setitem(sys.modules, "qdrant_client", qdrant)
    monkeypatch.setitem(sys.modules, "rank_bm25", bm25)
    monkeypatch.setattr(rag, "_english_stem", lambda token: token)
    monkeypatch.setattr(RagLibrary, "_index_fingerprint", lambda self: "offline-fixture")
    monkeypatch.setattr(RagLibrary, "_components", lambda self, **_kw: (_Embedder(), _Index(), _Splitter))
    monkeypatch.setattr(RagLibrary, "_index", lambda self, evidence, _index, _embedder: None)
    monkeypatch.setattr(
        RagLibrary,
        "_version_is_indexed",
        lambda self, version: bool(self._db.execute("SELECT 1 FROM rag_evidence WHERE version_id=?", (version,)).fetchone()),
    )
    source = tmp_path / "reference.txt"
    source.write_text("Anion exchange membrane with alkaline stability in potassium hydroxide.", encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"records": [{"file": source.name, "doi": "10.1/query-loop-fixture"}]}), encoding="utf-8")
    workspace = tmp_path / "reference-rag"
    with RagLibrary(workspace) as library:
        assert library.import_library(catalog)["imported"] == 1
        hit = library.search_evidence("anion exchange membrane", top_k=1)["items"][0]
        assert hit["text"] in source.read_text(encoding="utf-8")
        assert hit["locator"]["line_start"] == 1
    (workspace / "qdrant").mkdir(exist_ok=True)
    return workspace, hit


def _runtime(*, calls=4):
    return {
        "mode": "host", "data_mode": "live", "allow_network": True,
        "sources": {
            "openalex": {"anonymous": True, "page_size": 2, "max_pages": 1, "max_candidates": 2, "timeout_seconds": 5},
            "epo": {"page_size": 2, "max_pages": 1, "max_candidates": 2, "timeout_seconds": 5},
        },
        "budget": {"max_tasks": 8, "max_source_calls": calls, "max_pages_per_query": 1,
                   "max_source_bytes": 100000, "max_source_response_bytes": 100000},
    }


def _spec():
    return {"status": "ready", "project_id": "query-loop-fixture", "revision": 1,
            "research_question": "anion exchange membrane alkaline stability",
            "report_targets": ["technical_report", "literature_review"], "references": []}


def test_registered_reference_snapshot_is_frozen_into_core_planning_input(tmp_path, monkeypatch):
    workspace, hit = _reference_library(tmp_path, monkeypatch)
    snapshot = {"workspace_id": "workspace-a", "library_id": "library-a", "collection_id": "papers",
                "member_document_versions": [{"document_id": hit["document_id"], "current_version_id": hit["version_id"], "versions": [hit["version_id"]]}],
                "index_snapshot": {"index_status": "ready"}}
    evidence = {**hit, "visibility": "public", "context": [hit]}
    with InvestigationService(tmp_path / "core") as service:
        created = service.create_investigation(_spec(), _runtime(), {
            "registered_reference_snapshot": snapshot, "reference_evidence": [evidence],
            "reference_rag_diagnostics": {"mode": "hybrid", "lexical_hits": 1},
        })
        task = service.get_pending_tasks(created["run_id"])[0]["payload"]
        assert task["baseline_evidence"][0]["evidence_id"] == hit["evidence_id"]
        assert task["baseline_evidence"][0]["version_id"] == hit["version_id"]
        assert task["baseline_evidence"][0]["locator"] == hit["locator"]
        assert task["reference_rag_evidence_ids"] == [hit["evidence_id"]]
        assert service._run(created["run_id"])["scenario"]
        invalid = {**snapshot, "member_document_versions": [{"document_id": hit["document_id"], "current_version_id": "ver-expired"}]}
        with pytest.raises(InvestigationError, match="frozen library versions"):
            service.create_investigation(_spec(), _runtime(), {"registered_reference_snapshot": invalid, "reference_evidence": [evidence]})


class _Response:
    status_code = 200

    def __init__(self, body, status=200):
        self.body = body
        self.status_code = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def iter_content(self, _chunk_size):
        yield self.body


def test_rag_hit_plans_both_sources_and_reopens_without_new_requests(tmp_path, monkeypatch):
    workspace, hit = _reference_library(tmp_path, monkeypatch)
    private_source = tmp_path / "private-reference.txt"
    private_source.write_text("Anion exchange membrane alkaline stability, private fixture evidence.", encoding="utf-8")
    private_catalog = tmp_path / "private-catalog.json"
    private_catalog.write_text(json.dumps({"records": [{"file": private_source.name, "doi": "10.1/private-fixture"}]}), encoding="utf-8")
    with RagLibrary(workspace) as library:
        private_document_id = library.import_library(private_catalog)["documents"][0]["document_id"]
    calls = []

    class _OpenAlex:
        def __init__(self, _runtime, on_attempt):
            self.on_attempt = on_attempt

        def search(self, source, query, cursor=None):
            calls.append((source, query, cursor))
            self.on_attempt({"attempt": 1})
            return {"candidates": [{"document_id": "W1", "source": "openalex", "title": "Fixture paper"}],
                    "next_cursor": None, "complete": True}

    def ops_request(_method, url, **_kwargs):
        calls.append(("epo-http", url))
        if url.endswith("/accesstoken"):
            return _Response(b'{"access_token":"fixture-token","expires_in":1199}')
        return _Response(b'<ops:biblio-search xmlns:ops="http://ops.epo.org" total-result-count="3">'
                         b'<ops:search-result><exchange-document country="EP" doc-number="1234567" kind="A1"/>'
                         b'</ops:search-result></ops:biblio-search>')

    monkeypatch.setattr(investigation, "OpenAlexTransport", _OpenAlex)
    monkeypatch.setattr(investigation.requests, "request", ops_request)
    monkeypatch.setenv("EPO_CONSUMER_KEY", "fixture-key")
    monkeypatch.setenv("EPO_CONSUMER_SECRET", "fixture-secret")
    service_root = tmp_path / "investigation"
    with InvestigationService(service_root) as service:
        missing = service.create_investigation(_spec(), _runtime(), {"reference_rag_workspace": str(workspace)})
        missing_task = service.get_pending_tasks(missing["run_id"])[0]
        assert missing_task["payload"]["baseline_evidence"] == []
        assert missing_task["payload"]["reference_rag_diagnostics"]["evidence_gap"]
        assert service.status(missing["run_id"])["budget"]["reserved_source_calls"] == 0
        blocked = service.create_investigation(
            _spec(), _runtime(), {"reference_rag_workspace": str(workspace),
                                  "references": [{"document_id": hit["document_id"], "visibility": "confidential"}]}
        )
        assert blocked["status"] == "policy_blocked"
        assert service.get_pending_tasks(blocked["run_id"]) == []
        assert service.status(blocked["run_id"])["budget"]["reserved_source_calls"] == 0
        run = service.create_investigation(
            _spec(), _runtime(), {"reference_rag_workspace": str(workspace), "reference_rag_top_k": 1,
                                  "references": [{"document_id": hit["document_id"], "visibility": "public"}]}
        )["run_id"]
        planning = service.get_pending_tasks(run)[0]
        baseline = planning["payload"]["baseline_evidence"]
        assert len(baseline) == 1
        assert private_document_id not in {item["document_id"] for item in baseline}
        assert {key: baseline[0][key] for key in ("evidence_id", "document_id", "version_id", "locator")} == {
            key: hit[key] for key in ("evidence_id", "document_id", "version_id", "locator")
        }
        queries = [
            {"query_id": "paper-1", "source": "openalex", "query": "anion exchange membrane",
             "parent_query_id": None, "input_refs": [hit["evidence_id"]],
             "term_evidence": [{"term": term, "evidence_ref": hit["evidence_id"]}
                               for term in ("anion", "exchange", "membrane")]},
            {"query_id": "patent-1", "source": "epo", "query": 'ta="anion exchange" and ta=membrane',
             "parent_query_id": None, "input_refs": [hit["evidence_id"]],
             "term_evidence": [{"term": "anion exchange", "evidence_ref": hit["evidence_id"]},
                               {"term": "membrane", "evidence_ref": hit["evidence_id"]}]},
        ]
        service.submit_model_result(run, planning["task_id"], {"search_plan": {"queries": queries}}, planning["task_version"])
        service.advance_investigation(run)
        screens = service.get_pending_tasks(run)
        assert {task["role"] for task in screens} == {"paper_search", "patent_search"}
        assert {task["payload"]["query_id"] for task in screens} == {"paper-1", "patent-1"}
        coverage = service._coverage(run)
        assert {query["source"] for query in coverage["queries"]} == {"openalex", "epo"}
        assert all(query["input_refs"] == [hit["evidence_id"]] for query in coverage["queries"])
        assert coverage["complete"] is False
        assert next(query for query in coverage["queries"] if query["source"] == "epo")["status"] == "partial"
        for task in screens:
            answer = {"candidates": [{"document_id": candidate["document_id"], "relevance": "relevant", "reason": "fixture"}
                                     for candidate in task["payload"]["candidates"]]}
            service.submit_model_result(run, task["task_id"], answer, task["task_version"])
        revision = {"query_id": "patent-2", "source": "epo", "query": "ta=membrane and ta=stability",
                    "parent_query_id": "patent-1", "input_refs": [hit["evidence_id"], "query:patent-1"],
                    "term_evidence": [{"term": "membrane", "evidence_ref": hit["evidence_id"]},
                                      {"term": "stability", "evidence_ref": hit["evidence_id"]}],
                    "revision_reason": "Follow up the alkaline stability evidence gap."}
        service.add_epo_query(run, revision)
        budget = service.status(run)["budget"]
        assert budget["reserved_source_calls"] == 4
        assert budget["max_source_calls"] == 4
        assert service._coverage(run)["queries"][-1]["parent_query_id"] == "patent-1"
        version = "fixture-history"
        (service_root / "reports" / run / version).mkdir(parents=True)
        service._export_epo_history(run, version)
        history = json.loads((service_root / "reports" / run / version / "search-history.json").read_text(encoding="utf-8"))
        recorded = {query["query_id"]: query for query in history["queries"]}
        assert {(query["source"], query["query_id"]) for query in history["queries"]} == {
            ("openalex", "paper-1"), ("epo", "patent-1"), ("epo", "patent-2")}
        assert recorded["paper-1"]["term_evidence"] == queries[0]["term_evidence"]
        assert recorded["patent-1"]["term_evidence"] == queries[1]["term_evidence"]
        assert recorded["patent-2"]["term_evidence"] == revision["term_evidence"]
        assert recorded["patent-2"]["parent_query_id"] == "patent-1"
        assert recorded["patent-2"]["revision_reason"] == revision["revision_reason"]
        count = len(calls)
    with InvestigationService(service_root) as reopened:
        assert reopened.status(run)["budget"]["reserved_source_calls"] == 4
        assert reopened._search_live_pages(run, "paper-1", queries[0]["query"], _runtime())[1] == "complete"
        assert reopened._search_epo_pages(run, "patent-1", queries[1]["query"], _runtime())[1] == "partial"
    assert len(calls) == count


def test_missing_rag_hit_cannot_be_labeled_evidence_driven(tmp_path, monkeypatch):
    _reference_library(tmp_path, monkeypatch)
    workspace = tmp_path / "empty-reference-rag"
    with RagLibrary(workspace):
        pass
    (workspace / "qdrant").mkdir()
    with InvestigationService(tmp_path / "investigation") as service:
        created = service.create_investigation(
            _spec(), _runtime(), {"reference_rag_workspace": str(workspace)}
        )
        task = service.get_pending_tasks(created["run_id"])[0]
        assert task["payload"]["baseline_evidence"] == []
        assert task["payload"]["reference_rag_diagnostics"]["evidence_gap"]
        unsupported = {"query_id": "paper-1", "source": "openalex", "query": "anion exchange membrane",
                       "parent_query_id": None, "input_refs": ["invented-evidence"],
                       "term_evidence": [{"term": "anion exchange", "evidence_ref": "invented-evidence"}]}
        with pytest.raises(InvestigationError):
            service.submit_model_result(created["run_id"], task["task_id"],
                                        {"search_plan": {"queries": [unsupported]}}, task["task_version"])


def test_paper_and_patent_rag_versions_attach_to_one_analysis_snapshot(tmp_path, monkeypatch):
    _reference_library(tmp_path, monkeypatch)  # Local index and embedding substitutes only.
    paper_pdf = tmp_path / "paper.pdf"
    paper_pdf.write_bytes(b"%PDF-1.4 offline fixture")
    patent_xml = tmp_path / "patent.xml"
    patent_xml.write_text('<epo-evidence><p id="description:p1">Patent membrane evidence</p></epo-evidence>', encoding="utf-8")
    catalog = tmp_path / "discovery-catalog.json"
    catalog.write_text(json.dumps({"records": [{"file": paper_pdf.name, "doi": "10.1/paper"},
                                               {"file": patent_xml.name}]}), encoding="utf-8")
    with RagLibrary(tmp_path / "discovery-rag") as library:
        parse = library._parse
        library._parse = lambda path: (
            ([{"text": "Paper membrane evidence", "locator": {"kind": "pdf_page", "value": "1"},
               "section": "results", "role": "text"}], 1, "full_text", [])
            if path.suffix == ".pdf" else parse(path)
        )
        assert library.import_library(catalog)["imported"] == 2
        paper_hit = library.search_evidence("Paper membrane", top_k=1)["items"][0]
        patent_hit = library.search_evidence("Patent membrane", top_k=1)["items"][0]
    assert paper_hit["document_id"] != patent_hit["document_id"]
    assert paper_hit["version_id"] != patent_hit["version_id"]
    assert paper_hit["locator"]["kind"] == "pdf_page"
    assert patent_hit["locator"]["kind"] == "xml_node"

    paper = {"document_id": "W1", "version": "openalex-oa-pdf", "source": "openalex",
             "doi": "10.1/paper", "title": "Fixture paper"}
    patent_text = patent_xml.read_text(encoding="utf-8")
    patent = {"document_id": "EP1234567A1", "publication_id": "EP1234567A1", "source": "epo",
              "version": "epo-xml-v1", "content_type": "application/xml", "text": patent_text,
              "content_sha256": hashlib.sha256(patent_text.encode()).hexdigest()}
    with InvestigationService(tmp_path / "investigation") as service:
        run = service.create_investigation(_spec(), _runtime(), {"reference_evidence": []})["run_id"]
        for document in (paper, patent):
            service.db.execute("INSERT INTO discovery_documents VALUES (?,?,?)",
                               (run, document["document_id"], json.dumps(document)))
        service.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",
                           (run, "download-document", "W1", 1, "success",
                            json.dumps({"sha256": hashlib.sha256(paper_pdf.read_bytes()).hexdigest()})))
        service.db.execute("UPDATE investigations SET stage='analysis',status='waiting_model' WHERE id=?", (run,))
        service._task(run, "evidence_analysis", "extract", service._fact_payload(service._run(run), []))
        service.db.commit()
        mappings = [
            {"rag_document_id": paper_hit["document_id"], "rag_version_id": paper_hit["version_id"],
             "investigation_document_id": "W1", "investigation_version_id": paper["version"],
             "doi": paper["doi"], "sha256": hashlib.sha256(paper_pdf.read_bytes()).hexdigest()},
            {"rag_document_id": patent_hit["document_id"], "rag_version_id": patent_hit["version_id"],
             "investigation_document_id": patent["document_id"], "investigation_version_id": patent["version"],
             "publication_id": patent["publication_id"], "sha256": patent["content_sha256"]},
        ]
        hits = [paper_hit, patent_hit]
        assert service.attach_discovery_evidence(run, hits, mappings)["status"] == "attached"
        task = next(task for task in service.get_pending_tasks(run) if task["role"] == "evidence_analysis")
        facts = task["payload"]["evidence"]
        assert {(fact["document_id"], fact["version_id"]) for fact in facts} == {
            (hit["document_id"], hit["version_id"]) for hit in hits}
        for hit in hits:
            fact = next(fact for fact in facts if fact["evidence_id"] == hit["evidence_id"])
            assert fact["text"] == hit["text"] and fact["locator"] == hit["locator"]
            service._check_claim({"evidence_refs": [hit["evidence_id"]], "document_id": hit["document_id"],
                                  "version_id": hit["version_id"], "quote": hit["text"]}, facts)
        assert service.attach_discovery_evidence(run, hits, mappings)["status"] == "reused"


def test_source_limits_count_failed_and_pending_reservations_before_http(tmp_path, monkeypatch):
    runtime = _runtime(calls=20)
    sent = []

    def fake_ops(_method, url, **kwargs):
        sent.append((url, kwargs["params"]["q"]))
        return _Response(b"<fixture/>", status=503 if len(sent) == 7 else 200)

    class FakeOpenAlex:
        def __init__(self, _runtime, on_attempt):
            self.on_attempt = on_attempt

        def search(self, _source, _query, _cursor=None):
            self.on_attempt({"attempt": 1})
            sent.append(("openalex", len([call for call in sent if call[0] == "openalex"])))
            if len([call for call in sent if call[0] == "openalex"]) == 1:
                raise SourceError("RH_SOURCE_TIMEOUT", "fixture timeout")
            return {"candidates": [], "next_cursor": None, "complete": True}

    monkeypatch.setattr(investigation.requests, "request", fake_ops)
    monkeypatch.setattr(investigation, "OpenAlexTransport", FakeOpenAlex)
    with InvestigationService(tmp_path / "budget-run") as service:
        run = service.create_investigation(
            _spec(), runtime, {"reference_evidence": [], "source_call_limits": {"epo": 8, "openalex": 2}}
        )["run_id"]
        for number in range(1, 8):
            if number == 7:
                with pytest.raises(SourceError):
                    service._epo_request(run, "search", "GET", "https://ops.epo.org/fixture",
                                         params={"q": f"ta=fixture{number}"})
            else:
                service._epo_request(run, "search", "GET", "https://ops.epo.org/fixture",
                                     params={"q": f"ta=fixture{number}"})
        budget = service.status(run)["budget"]
        budget["reserved_source_calls"] += 1
        service.db.execute("UPDATE investigations SET budget=? WHERE id=?", (json.dumps(budget), run))
        service.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",
                           (run, "epo-http", "search:pending-fixture", 1, "pending", "{}"))
        service.db.commit()
        with pytest.raises(SourceError) as error:
            service._epo_request(run, "search", "GET", "https://ops.epo.org/fixture",
                                 params={"q": "ta=ninth"})
        assert error.value.code == "RH_SOURCE_BUDGET"
        assert len([call for call in sent if call[0] != "openalex"]) == 7
        assert service.status(run)["budget"]["reserved_source_calls"] == 8

        found, status, reason = service._search_live_pages(run, "paper-budget", "membrane", runtime)
        assert found == [] and status == "complete" and reason is None
        assert service.status(run)["budget"]["reserved_openalex_calls"] == 2
        assert service._search_live_pages(run, "paper-over-budget", "ionomer", runtime)[1:] == (
            "partial", "RH_SOURCE_BUDGET")
        assert len([call for call in sent if call[0] == "openalex"]) == 2
        assert service.status(run)["budget"]["reserved_openalex_calls"] == 2


def test_direct_pdf_is_tried_before_landing_and_two_redirects_remain_partial(tmp_path, monkeypatch):
    workspace, hit = _reference_library(tmp_path, monkeypatch)
    direct = "https://files.example/paper.pdf"
    landing = "https://doi.org/10.1/paper"
    seen = []

    class FakeSession:
        def get(self, url, **_kwargs):
            seen.append(url)
            return SimpleNamespace(status_code=302, headers={"Location": "https://files.example/redirected.pdf"},
                                   close=lambda: None)

    monkeypatch.setattr(literature.requests, "Session", FakeSession)
    monkeypatch.setattr(literature, "_safe_url", lambda value: value)
    runtime = _runtime()
    runtime["budget"].update({"max_downloads": 1, "max_download_calls": 2, "max_download_bytes": 100000})
    original_locations = [
        {"is_oa": True, "pdf_url": None, "landing_page_url": landing},
        {"is_oa": True, "pdf_url": direct, "landing_page_url": None},
    ]
    paper = {"document_id": "W1", "source_id": "W1", "source": "openalex", "version": "openalex-metadata",
             "title": "Fixture paper", "doi": "10.1/paper", "year": 2024, "authors": [], "type": "article",
             "locations": original_locations}
    with InvestigationService(tmp_path / "download-run") as service:
        run = service.create_investigation(
            _spec(), runtime, {"reference_rag_workspace": str(workspace),
                               "references": [{"document_id": hit["document_id"], "visibility": "public"}]}
        )["run_id"]
        service.db.execute("INSERT INTO discovery_documents VALUES (?,?,?)", (run, "W1", json.dumps(paper)))
        service.db.commit()
        issues = service._acquire_live_documents(run, runtime, ["W1"])
        assert seen == [direct, "https://files.example/redirected.pdf"]
        budget = service.status(run)["budget"]
        assert budget["reserved_download_calls"] == 2 and budget["received_download_bytes"] == 0
        assert [row[0] for row in service.db.execute(
            "SELECT status FROM source_attempts WHERE run_id=? AND query_id='download' ORDER BY rowid", (run,)
        )] == ["RH_SOURCE_HTTP_302", "RH_SOURCE_HTTP_302"]
        assert any(issue["code"] == "RH_FULLTEXT_GAP" for issue in issues)
        stored = json.loads(service.db.execute(
            "SELECT payload FROM discovery_documents WHERE run_id=? AND document_id='W1'", (run,)
        ).fetchone()[0])
        assert stored["version"] == "openalex-metadata" and stored["locations"] == original_locations
        catalog = json.loads((service.root / "downloads" / run / "catalog.json").read_text(encoding="utf-8"))
        assert catalog["valid_pdf_count"] == 0
        assert catalog["records"][0]["record"]["locations"][0]["pdf_url"] == direct
