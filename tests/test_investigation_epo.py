"""Synthetic OPS protocol fixtures; no live source call is made by this module."""
import json

import pytest

from research_harness.epo import parse_family, parse_section
from research_harness.investigation import InvestigationService
from research_harness.investigation_contracts import validate_runtime
from research_harness.investigation_sources import SourceError, normalize
from research_harness.rag import RagLibrary


def runtime(calls=20):
    return {"mode":"host","data_mode":"live","allow_network":True,
            "sources":{"epo":{"page_size":5,"max_pages":2,"max_candidates":20,"timeout_seconds":30}},
            "budget":{"max_tasks":10,"max_source_calls":calls,"max_source_bytes":20*1024*1024,
                      "max_source_response_bytes":5*1024*1024,"max_pages_per_query":2}}


def spec():
    return {"status":"ready","project_id":"fixture","revision":1,"research_question":"AEM",
            "report_targets":["technical_report","literature_review"],"references":[]}


SEARCH=b'''<ops:world-patent-data xmlns:ops="http://ops.epo.org"><ops:biblio-search total-result-count="2"><ops:search-result><exchange-documents><exchange-document country="EP" doc-number="1234567" kind="A1" family-id="F1"><invention-title lang="en">AEM polymer</invention-title></exchange-document><exchange-document country="EP" doc-number="1234567" kind="B1" family-id="F1"/></exchange-documents></ops:search-result></ops:biblio-search></ops:world-patent-data>'''
FAMILY=b'''<ops:world-patent-data xmlns:ops="http://ops.epo.org"><ops:patent-family><ops:family-member><publication-reference><document-id document-id-type="docdb"><country>EP</country><doc-number>1234567</doc-number><kind>A1</kind></document-id></publication-reference></ops:family-member><ops:family-member><publication-reference><document-id document-id-type="docdb"><country>EP</country><doc-number>1234567</doc-number><kind>B1</kind></document-id></publication-reference></ops:family-member></ops:patent-family></ops:world-patent-data>'''


class Response:
    def __init__(self, body, status=200): self.body=body; self.status_code=status
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def iter_content(self, chunk_size): yield self.body


def fake_ops(calls):
    def request(method,url,**kw):
        calls.append((method,url,kw))
        if url.endswith("/accesstoken"):
            return Response(b'{"access_token":"SENSITIVE-TOKEN","expires_in":1199}')
        if url.endswith("/search/biblio"): return Response(SEARCH)
        if "/family/" in url: return Response(FAMILY)
        if url.endswith("/fulltext"):
            kind="B1" if "B1" in url else "A1"
            return Response(f'<ops:world-patent-data xmlns:ops="http://ops.epo.org"><ops:fulltext-inquiry><ops:inquiry-result><publication-reference><document-id document-id-type="docdb"><country>EP</country><doc-number>1234567</doc-number><kind>{kind}</kind></document-id></publication-reference><ops:fulltext-instance desc="claims"/><ops:fulltext-instance desc="description"/></ops:inquiry-result></ops:fulltext-inquiry></ops:world-patent-data>'.encode())
        pub="EP1234567B1" if "B1" in url else "EP1234567A1"
        kind="B1" if "B1" in url else "A1"
        section="claims" if url.endswith("claims") else "description"
        node="claim" if section=="claims" else "p"
        body=f'<fulltext-document country="EP" doc-number="1234567" kind="{kind}"><{section} lang="EN"><{node} id="p1">{pub} {section} text</{node}></{section}></fulltext-document>'.encode()
        return Response(body)
    return request


def test_epo_only_search_family_versions_and_ledger(monkeypatch,tmp_path):
    calls=[]; monkeypatch.setattr("research_harness.investigation.requests.request",fake_ops(calls))
    monkeypatch.setenv("EPO_CONSUMER_KEY","fixture-key"); monkeypatch.setenv("EPO_CONSUMER_SECRET","fixture-secret")
    config=runtime(); validate_runtime(config)
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(spec(),config,{"reference_evidence":[]})["run_id"]
        service.db.execute("INSERT INTO source_queries VALUES (?,?,?,?,?,?,?,?)",(run,"Q1","epo","ta=membrane",None,"[]","pending",None)); service.db.commit()
        found,status,_=service._search_epo_pages(run,"Q1","ta=membrane",config)
        assert status=="complete" and [x["document_id"] for x in found]==["EP1234567A1","EP1234567B1"]
        assert service._search_epo_pages(run,"Q1","ta=membrane",config)[1]=="complete"
        assert len(calls)==2  # auth and one CQL page, then cached page
        assert service.status(run)["budget"]["reserved_source_calls"] == 2
        assert service.db.execute("SELECT COUNT(*) FROM source_attempts WHERE run_id=? AND query_id='epo-http'",(run,)).fetchone()[0] == 2
        issues=service._acquire_epo_documents(run,config,["EP1234567A1","EP1234567B1"])
        assert not issues
        assert any("EP1234567.A1/fulltext" in url for _,url,_ in calls)
        sources={x["document_id"]:x for x in service._sources(service._run(run))}
        assert sources["EP1234567A1"]["version"]!=sources["EP1234567B1"]["version"]
        assert {x["locator"]["value"] for x in normalize(sources["EP1234567A1"])}=={"claims:p1","description:p1"}
        xml_file=tmp_path/"patent.xml"; xml_file.write_text(sources["EP1234567A1"]["text"],encoding="utf-8")
        blocks,_,_,_=RagLibrary.__new__(RagLibrary)._parse(xml_file)
        assert {x["locator"]["value"] for x in blocks}=={"claims:p1","description:p1"}
        assert service.status(run)["budget"]["reserved_source_calls"]==8
        records=[json.loads(x["result"]) for x in service.db.execute("SELECT result FROM source_attempts WHERE run_id=? AND query_id='epo-http'",(run,))]
        assert all("SENSITIVE-TOKEN" not in json.dumps(x) and "fixture-secret" not in json.dumps(x) for x in records)
        assert all((tmp_path/x["raw_xml_path"]).exists() for x in records if x["operation"]!="auth")


def test_epo_failure_and_budget_are_distinct_from_empty_success(monkeypatch,tmp_path):
    calls=[]; monkeypatch.setattr("research_harness.investigation.requests.request",fake_ops(calls))
    monkeypatch.setenv("EPO_CONSUMER_KEY","key"); monkeypatch.setenv("EPO_CONSUMER_SECRET","secret")
    with InvestigationService(tmp_path) as service:
        config=runtime(calls=1); run=service.create_investigation(spec(),config,{"reference_evidence":[]})["run_id"]
        result=service._search_epo_pages(run,"Q1","ta=membrane",config)
        assert result[1:]==("partial","RH_SOURCE_BUDGET") and len(calls)==1
        assert service.status(run)["budget"]["reserved_source_calls"]==1
    with InvestigationService(tmp_path/"missing") as service:
        monkeypatch.delenv("EPO_CONSUMER_KEY")
        run=service.create_investigation(spec(),runtime(),{"reference_evidence":[]})["run_id"]
        assert service._search_epo_pages(run,"Q1","ta=membrane",runtime())[1:]==("partial","RH_SOURCE_CREDENTIAL")
        assert service.status(run)["budget"]["reserved_source_calls"]==0


def test_version_mismatch_and_extended_family_semantics():
    family=parse_family(FAMILY)
    assert family["family_type"]=="inpadoc_extended" and len(family["members"])==2
    with pytest.raises(SourceError,match="another publication"):
        parse_section(b'<fulltext-document country="EP" doc-number="1234567" kind="B1"><claims><claim id="1">text</claim></claims></fulltext-document>',"claims","EP1234567A1")
    parts=parse_section(b'<fulltext-document country="EP" doc-number="1234567" kind="A1"><description><p>Context</p><table><p>10</p></table><example><p id="e1">Measured example</p></example></description></fulltext-document>',"description","EP1234567A1")
    assert len(parts)==2 and parts[0]["locator"]["kind"]=="epo_xpath"
    assert parts[1]["section"]=="example" and all(x["table_gap"] for x in parts)


def test_patent_attach_uses_publication_and_xml_fingerprint(monkeypatch,tmp_path):
    calls=[]; monkeypatch.setattr("research_harness.investigation.requests.request",fake_ops(calls))
    monkeypatch.setenv("EPO_CONSUMER_KEY","fixture-key"); monkeypatch.setenv("EPO_CONSUMER_SECRET","fixture-secret")
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(spec(),runtime(),{"reference_evidence":[]})["run_id"]
        service._search_epo_pages(run,"Q1","ta=membrane",runtime())
        assert not service._acquire_epo_documents(run,runtime(),["EP1234567A1"])
        source=next(x for x in service._sources(service._run(run)) if x.get("publication_id")=="EP1234567A1")
        service.db.execute("UPDATE investigations SET stage='analysis',status='waiting_model' WHERE id=?",(run,))
        service.db.commit(); service._task(run,"evidence_analysis","extract",service._fact_payload(service._run(run),[]))
        rag={"evidence_id":"rag-1","document_id":"rag-patent","version_id":"rag-v1","text":"EP1234567A1 claims text","locator":{"kind":"xml_node","value":"claims:p1"}}
        mapping={"rag_document_id":"rag-patent","rag_version_id":"rag-v1","investigation_document_id":"EP1234567A1","investigation_version_id":source["version"],"publication_id":"EP1234567A1","sha256":source["content_sha256"]}
        assert service.attach_discovery_evidence(run,[rag],[mapping])["status"]=="attached"
        assert service.attach_discovery_evidence(run,[rag],[mapping])["status"]=="reused"
        bad=dict(mapping,publication_id="EP1234567B1")
        with pytest.raises(Exception,match="already attached|fingerprint"):
            service.attach_discovery_evidence(run,[rag],[bad])


def test_search_history_is_read_only_and_reopenable(monkeypatch,tmp_path):
    calls=[]; monkeypatch.setattr("research_harness.investigation.requests.request",fake_ops(calls))
    monkeypatch.setenv("EPO_CONSUMER_KEY","fixture-key"); monkeypatch.setenv("EPO_CONSUMER_SECRET","fixture-secret")
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(spec(),runtime(),{"reference_evidence":[]})["run_id"]
        service.db.execute("INSERT INTO source_queries VALUES (?,?,?,?,?,?,?,?)",(run,"Q1","epo","ta=membrane",None,"[]","pending",None))
        service.db.execute("INSERT INTO epo_query_details VALUES (?,?,?)",(run,"Q1",json.dumps({"intent":"topic","terms_basis":"approved Q1"})))
        service.db.commit(); service._search_epo_pages(run,"Q1","ta=membrane",runtime())
        version="run-"+run; (tmp_path/"reports"/run/version).mkdir(parents=True)
        first=service._export_epo_history(run,version)
        assert len(first)==2
        history=json.loads((tmp_path/first[0]["path"]).read_text(encoding="utf-8"))
        assert history["queries"][0]["attempts"][0]["candidate_ids"]==["EP1234567A1","EP1234567B1"]
        count=len(calls)
    with InvestigationService(tmp_path) as service:
        assert service._export_epo_history(run,version)==first
    assert len(calls)==count


@pytest.mark.parametrize("http_status,expected",[(401,"RH_SOURCE_AUTHENTICATION"),(429,"RH_SOURCE_RATE_LIMIT")])
def test_auth_failure_is_recorded_without_search(monkeypatch,tmp_path,http_status,expected):
    calls=[]
    def rejected(method,url,**kw):
        calls.append(url)
        return Response(b'<error>rejected</error>',http_status)
    monkeypatch.setattr("research_harness.investigation.requests.request",rejected)
    monkeypatch.setenv("EPO_CONSUMER_KEY","key"); monkeypatch.setenv("EPO_CONSUMER_SECRET","secret")
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(spec(),runtime(),{"reference_evidence":[]})["run_id"]
        assert service._search_epo_pages(run,"Q1","ta=membrane",runtime())[1:]==("partial",expected)
        budget=service.status(run)["budget"]
        assert budget["reserved_source_calls"]==1 and budget["received_source_bytes"]==len(b'<error>rejected</error>')
        assert len(calls)==1


def test_empty_success_and_page_truncation(monkeypatch,tmp_path):
    monkeypatch.setenv("EPO_CONSUMER_KEY","key"); monkeypatch.setenv("EPO_CONSUMER_SECRET","secret")
    count=[]
    def empty(method,url,**kw):
        count.append(url)
        return Response(b'{"access_token":"token"}' if url.endswith("accesstoken") else b'<ops:biblio-search xmlns:ops="http://ops.epo.org" total-result-count="0"><ops:search-result/></ops:biblio-search>')
    monkeypatch.setattr("research_harness.investigation.requests.request",empty)
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(spec(),runtime(),{"reference_evidence":[]})["run_id"]
        assert service._search_epo_pages(run,"Q1","ta=membrane",runtime())==([],"complete",None)
        assert len(count)==2
    def many(method,url,**kw):
        count.append(url)
        body=b'<ops:biblio-search xmlns:ops="http://ops.epo.org" total-result-count="100"><ops:search-result><exchange-document country="EP" doc-number="1234567" kind="A1"/></ops:search-result></ops:biblio-search>'
        return Response(b'{"access_token":"token"}' if url.endswith("accesstoken") else body)
    monkeypatch.setattr("research_harness.investigation.requests.request",many)
    with InvestigationService(tmp_path/"paged") as service:
        run=service.create_investigation(spec(),runtime(),{"reference_evidence":[]})["run_id"]
        assert service._search_epo_pages(run,"Q1","ta=membrane",runtime())[1:]==("partial","page or candidate limit")
        assert service.status(run)["budget"]["reserved_source_calls"]==3


def test_single_response_limit_accounts_received_bytes(monkeypatch,tmp_path):
    monkeypatch.setenv("EPO_CONSUMER_KEY","key"); monkeypatch.setenv("EPO_CONSUMER_SECRET","secret")
    monkeypatch.setattr("research_harness.investigation.requests.request",fake_ops([]))
    config=runtime(); config["budget"]["max_source_response_bytes"]=100
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(spec(),config,{"reference_evidence":[]})["run_id"]
        assert service._search_epo_pages(run,"Q1","ta=membrane",config)[1:]==("partial","RH_SOURCE_BYTE_BUDGET")
        assert service.status(run)["budget"]["reserved_source_calls"]==2
        assert service.status(run)["budget"]["received_source_bytes"]>100


def test_query_revision_stays_in_one_run_and_budget(monkeypatch,tmp_path):
    calls=[]; monkeypatch.setattr("research_harness.investigation.requests.request",fake_ops(calls))
    monkeypatch.setenv("EPO_CONSUMER_KEY","key"); monkeypatch.setenv("EPO_CONSUMER_SECRET","secret")
    with InvestigationService(tmp_path) as service:
        reference={"evidence_id":"ref-1","document_id":"baseline-1","version_id":"v1","text":"membrane ionomer","locator":{"kind":"page","value":"1"},"visibility":"public"}
        run=service.create_investigation(spec(),runtime(),{"reference_evidence":[reference]})["run_id"]
        planning=service.get_pending_tasks(run)[0]
        q1={"query_id":"Q1","source":"epo","query":"ta=membrane","input_refs":["ref-1"],"parent_query_id":None}
        service.submit_model_result(run,planning["task_id"],{"search_plan":{"queries":[q1]}},planning["task_version"])
        service.advance_investigation(run)
        screen=service.get_pending_tasks(run)[0]
        service.submit_model_result(run,screen["task_id"],{"candidates":[{"document_id":x["document_id"],"relevance":"relevant","reason":"fixture"} for x in screen["payload"]["candidates"]]},screen["task_version"])
        q2={"query_id":"Q2","source":"epo","query":"ta=ionomer","input_refs":["ref-1"],"parent_query_id":"Q1","revision_reason":"narrow ionomer term"}
        assert service.add_epo_query(run,q2)["candidate_count"]==2
        assert service.status(run)["budget"]["reserved_source_calls"]==3
        assert len(service.get_pending_tasks(run))==1


def test_saved_xml_recovery_updates_pending_snapshot_without_http(monkeypatch,tmp_path):
    calls=[]; monkeypatch.setattr("research_harness.investigation.requests.request",fake_ops(calls))
    monkeypatch.setenv("EPO_CONSUMER_KEY","key"); monkeypatch.setenv("EPO_CONSUMER_SECRET","secret")
    with InvestigationService(tmp_path) as service:
        run=service.create_investigation(spec(),runtime(),{"reference_evidence":[]})["run_id"]
        service._search_epo_pages(run,"Q1","ta=membrane",runtime())
        service._acquire_epo_documents(run,runtime(),["EP1234567A1"])
        original=next(x for x in service._sources(service._run(run)) if x.get("publication_id")=="EP1234567A1")
        metadata={key:value for key,value in original.items() if key not in {"content_type","text","epo_sections","source_xml","content_sha256"}}
        service.db.execute("UPDATE discovery_documents SET payload=? WHERE run_id=? AND document_id=?",(json.dumps(metadata),run,"EP1234567A1"))
        service.db.execute("UPDATE investigations SET stage='analysis',status='waiting_model' WHERE id=?",(run,)); service.db.commit()
        service._task(run,"evidence_analysis","extract",{"evidence":[],"acquisition_issues":[{"code":"RH_SOURCE_VERSION_UNVERIFIED","document_id":"EP1234567A1"}]})
        count=len(calls)
        restored=service.recover_epo_xml(run,"EP1234567A1")
        assert restored["status"]=="recovered" and restored["paragraphs"]==2
        assert len(calls)==count and service.recover_epo_xml(run,"EP1234567A1")["status"]=="reused"
        task=next(x for x in service.get_pending_tasks(run) if x["role"]=="evidence_analysis")
        assert task["task_version"]==2 and not task["payload"]["acquisition_issues"]
        source=next(x for x in service._sources(service._run(run)) if x.get("publication_id")=="EP1234567A1")
        assert source["content_sha256"]==original["content_sha256"]
