import json

import pytest

from research_harness.investigation import InvestigationError, InvestigationService


def _runtime():
    return {"mode":"host","data_mode":"live","allow_network":True,"budget":{"max_tasks":8},"sources":{"openalex":{"anonymous":True}}}


def _spec():
    return {"status":"ready","project_id":"bridge","revision":1,"research_question":"q","report_targets":["technical_report"],"references":[]}


def _ready_service(tmp_path):
    service=InvestigationService(tmp_path)
    baseline={"evidence_id":"base-1","document_id":"base-doc","version_id":"base-v1","text":"baseline fact","locator":{"kind":"pdf_page","value":"1"}}
    run=service.create_investigation(_spec(),_runtime(),{"reference_evidence":[baseline],"reference_bibliography":[{"id":"base-doc","title":"Baseline"}]})["run_id"]
    source={"document_id":"W1","version":"openalex-oa-pdf","source":"openalex","doi":"10.1/example","title":"Candidate","year":2024,"type":"article"}
    service.db.execute("INSERT INTO discovery_documents VALUES (?,?,?)",(run,"W1",json.dumps(source)))
    service.db.execute("INSERT INTO source_attempts VALUES (?,?,?,?,?,?)",(run,"download-document","W1",1,"success",json.dumps({"sha256":"abc"})))
    page={"evidence_id":"page-1","document_id":"W1","version_id":"openalex-oa-pdf","text":"downloaded page","quote":"downloaded page","locator":{"kind":"pdf_page","value":"1"}}
    service.db.execute("INSERT INTO discovery_evidence VALUES (?,?,?,?,?,?,?)",("page-1",run,"W1","openalex-oa-pdf",json.dumps(page),"public",None))
    service.db.execute("UPDATE investigations SET stage='analysis',status='waiting_model' WHERE id=?",(run,))
    service._task(run,"evidence_analysis","extract",service._fact_payload(service._run(run),[page]))
    service.db.commit()
    return service,run


def test_bridge_binds_baseline_acquisition_and_rag_facts_idempotently(tmp_path):
    service,run=_ready_service(tmp_path)
    rag={"evidence_id":"rag-1","document_id":"rag-doc","version_id":"rag-v1","parse_revision_id":"pr-rag-1","source_sha256":"source-hash","text":"Docling fact","locator":{"page":1,"pages":[1],"provenance":[{"page":1,"bbox":{"l":1,"t":1,"r":2,"b":2}}]}}
    mapping={"investigation_document_id":"W1","investigation_version_id":"openalex-oa-pdf","doi":"10.1/example","sha256":"abc","rag_document_id":"rag-doc","rag_version_id":"rag-v1","parse_revision_id":"pr-rag-1","source_sha256":"source-hash"}
    try:
        old_task=next(item for item in service.get_pending_tasks(run) if item["role"] == "evidence_analysis")
        assert service.attach_discovery_evidence(run,[rag],[mapping],[{"id":"rag-doc","title":"Candidate"}])["status"] == "attached"
        task=next(item["payload"] for item in service.get_pending_tasks(run) if item["role"] == "evidence_analysis")
        assert {item["evidence_id"] for item in task["evidence"]} == {"base-1","page-1","rag-1"}
        assert next(item for item in task["evidence"] if item["evidence_id"]=="rag-1")["parse_revision_id"] == "pr-rag-1"
        saved_mapping=service.db.execute("SELECT payload FROM attached_discovery_evidence WHERE run_id=?",(run,)).fetchone()
        assert json.loads(saved_mapping["payload"])["mappings"][0]["source_sha256"] == "source-hash"
        assert {item["id"] for item in task["bibliography"]} == {"base-doc","W1","rag-doc"}
        service._check_claim({"evidence_refs":["base-1"],"document_id":"base-doc","version_id":"base-v1","quote":"baseline fact"},task["evidence"])
        service._check_claim({"evidence_refs":["rag-1"],"document_id":"rag-doc","version_id":"rag-v1","parse_revision_id":"pr-rag-1","quote":"Docling fact"},task["evidence"])
        assert service.attach_discovery_evidence(run,[rag],[mapping],[{"id":"rag-doc","title":"Candidate"}])["status"] == "reused"
        with pytest.raises(InvestigationError, match="task version is stale"):
            service.submit_model_result(run,old_task["task_id"],{},old_task["task_version"])
        with pytest.raises(InvestigationError, match="already attached"):
            service.attach_discovery_evidence(run,[{**rag,"text":"Different Docling fact"}],[mapping])
        task_id=next(item for item in service.get_pending_tasks(run) if item["role"] == "evidence_analysis")
        service.db.execute("UPDATE model_tasks SET status='completed' WHERE id=?",(task_id["task_id"],)); service.db.commit()
        with pytest.raises(InvestigationError, match="before analysis submission"):
            service.attach_discovery_evidence(run,[rag],[mapping])
    finally:
        service.close()


def test_bridge_rejects_mapping_without_download_identity(tmp_path):
    service,run=_ready_service(tmp_path)
    rag={"evidence_id":"rag-1","document_id":"rag-doc","version_id":"rag-v1","text":"Docling fact","locator":{"kind":"pdf_page","value":"1"}}
    mapping={"investigation_document_id":"W1","investigation_version_id":"openalex-oa-pdf","doi":"10.1/example","sha256":"wrong","rag_document_id":"rag-doc","rag_version_id":"rag-v1"}
    try:
        with pytest.raises(InvestigationError, match="fingerprint"):
            service.attach_discovery_evidence(run,[rag],[mapping])
    finally:
        service.close()


def test_bridge_rejects_after_business_submission_and_keeps_run_local_facts(tmp_path):
    service,run=_ready_service(tmp_path)
    rag={"evidence_id":"rag-1","document_id":"rag-doc","version_id":"rag-v1","text":"Docling fact","locator":{"kind":"pdf_page","value":"1"}}
    mapping={"investigation_document_id":"W1","investigation_version_id":"openalex-oa-pdf","doi":"10.1/example","sha256":"abc","rag_document_id":"rag-doc","rag_version_id":"rag-v1"}
    try:
        service._task(run,"business_judgment","judge",{"documents":[],"evidence":[]})
        business=next(item for item in service.get_pending_tasks(run) if item["role"] == "business_judgment")
        service.db.execute("UPDATE model_tasks SET status='completed' WHERE id=?",(business["task_id"],)); service.db.commit()
        with pytest.raises(InvestigationError, match="business judgment"):
            service.attach_discovery_evidence(run,[rag],[mapping])
        other=service.create_investigation(_spec(),_runtime(),{"reference_evidence":[]})["run_id"]
        page={"evidence_id":"page-1","document_id":"W1","version_id":"openalex-oa-pdf","text":"downloaded page","locator":{"kind":"pdf_page","value":"1"}}
        service.db.execute("INSERT OR IGNORE INTO discovery_evidence VALUES (?,?,?,?,?,?,?)",("page-1",other,"W1","openalex-oa-pdf",json.dumps(page),"public",None)); service.db.commit()
        assert service._fact_payload(service._run(other),[page])["evidence"] == [page]
    finally:
        service.close()
