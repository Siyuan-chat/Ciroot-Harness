from importlib import resources
from pathlib import Path

import pytest

from research_harness.investigation import InvestigationError, InvestigationService
from research_harness.investigation import get_task_schema


def _spec():
    return {"status":"ready","project_id":"parse-binding","revision":1,
            "research_question":"frozen parse evidence","report_targets":["technical_report"],"references":[]}


def _runtime():
    return {"mode":"host","data_mode":"live","allow_network":True,
            "sources":{"openalex":{"anonymous":True}},"budget":{"max_tasks":8}}


def _evidence(revision, text):
    return {"evidence_id":f"ev-{revision}","document_id":"doc-1","version_id":"ver-1",
            "parse_revision_id":revision,"source_sha256":"same-source-sha256","text":text,
            "locator":{"kind":"text_line","value":"line-1"}}


def test_registered_parse_revision_is_frozen_and_claim_must_match(tmp_path):
    old, new = _evidence("pr-old", "old parsed text"), _evidence("pr-new", "new parsed text")
    common = {"workspace_id":"ws","library_id":"lib","collection_id":"papers",
              "index_snapshot":{"index_status":"ready"}}
    old_snapshot = {**common,"member_document_versions":[{"document_id":"doc-1","current_version_id":"ver-1",
                                                           "current_parse_revision_id":"pr-old","versions":["ver-1"]}]}
    new_snapshot = {**common,"member_document_versions":[{"document_id":"doc-1","current_version_id":"ver-1",
                                                           "current_parse_revision_id":"pr-new","versions":["ver-1"]}]}
    with InvestigationService(tmp_path / "core") as service:
        old_run = service.create_investigation(_spec(),_runtime(),
            {"registered_reference_snapshot":old_snapshot,"reference_evidence":[old]})["run_id"]
        old_task = service.get_pending_tasks(old_run)[0]["payload"]
        new_run = service.create_investigation(_spec(),_runtime(),
            {"registered_reference_snapshot":new_snapshot,"reference_evidence":[new]})["run_id"]
        new_task = service.get_pending_tasks(new_run)[0]["payload"]

        assert old_task["baseline_evidence"] == [old]
        assert new_task["baseline_evidence"] == [new]
        assert old_task["baseline_evidence"][0]["text"] == "old parsed text"
        claim = {"evidence_refs":[old["evidence_id"]],"document_id":"doc-1","version_id":"ver-1",
                 "parse_revision_id":"pr-old","quote":"old parsed text"}
        service._check_claim(claim,old_task["baseline_evidence"],require_parse_revision=True)
        with pytest.raises(InvestigationError,match="parse revision"):
            service._check_claim({**claim,"parse_revision_id":"pr-new"},old_task["baseline_evidence"],require_parse_revision=True)
        with pytest.raises(InvestigationError,match="parse revision"):
            service._check_claim({key:value for key,value in claim.items() if key!="parse_revision_id"},old_task["baseline_evidence"],require_parse_revision=True)
        service._task(old_run,"evidence_analysis","extract",{"evidence":old_task["baseline_evidence"]})
        analysis_task=service.db.execute("SELECT id FROM model_tasks WHERE run_id=? AND role='evidence_analysis' ORDER BY created DESC LIMIT 1",(old_run,)).fetchone()
        service.db.execute("UPDATE model_tasks SET status='completed',result=? WHERE id=?",
                           ('{"findings":[{"finding":"old parse","evidence_ids":["ev-pr-old"]}]}',analysis_task["id"]))
        service.db.commit()
        submission={"claims":[{"claim":"old parse","finding_refs":[0],"evidence_refs":["ev-pr-old"],
                                "quote":"old parsed text","document_id":"doc-1","version_id":"ver-1",
                                "parse_revision_id":"pr-old"}]}
        service._refs({"run_id":old_run,"role":"synthesis","payload":"{}"},submission)
        with pytest.raises(InvestigationError,match="parse revision"):
            service._refs({"run_id":old_run,"role":"synthesis","payload":"{}"},
                          {"claims":[{**submission["claims"][0],"parse_revision_id":"pr-new"}]})


def test_registered_snapshot_rejects_evidence_from_another_parse_revision(tmp_path):
    evidence = _evidence("pr-new","new parsed text")
    snapshot = {"workspace_id":"ws","library_id":"lib","collection_id":"papers",
                "member_document_versions":[{"document_id":"doc-1","current_version_id":"ver-1",
                                              "current_parse_revision_id":"pr-old","versions":["ver-1"]}],
                "index_snapshot":{"index_status":"ready"}}
    with InvestigationService(tmp_path / "core") as service:
        with pytest.raises(InvestigationError,match="parse revisions"):
            service.create_investigation(_spec(),_runtime(),
                {"registered_reference_snapshot":snapshot,"reference_evidence":[evidence]})


def test_legacy_evidence_without_parse_revision_remains_compatible(tmp_path):
    evidence = {key:value for key,value in _evidence("pr-old","legacy text").items()
                if key!="parse_revision_id"}
    claim = {"evidence_refs":[evidence["evidence_id"]],"document_id":"doc-1","version_id":"ver-1",
             "quote":"legacy text"}
    with InvestigationService(tmp_path / "core") as service:
        service._check_claim(claim,[evidence])


def test_synthesis_contract_and_prompt_expose_parse_revision_binding():
    schema=get_task_schema("synthesis")
    claim=schema["properties"]["claims"]["items"]
    assert claim["properties"]["parse_revision_id"] == {"type":"string","minLength":1}
    prompt=resources.files("research_harness").joinpath("prompts","investigation","synthesis.md").read_text(encoding="utf-8")
    assert "copy that exact value" in prompt
    assert Path("schemas/investigation-task.schema.json").read_bytes() == Path("src/research_harness/schemas/investigation-task.schema.json").read_bytes()
