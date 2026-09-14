import pytest

from research_harness.errors import HarnessError
from research_harness.investigation_report_data import build_report_data, validate_claims
from research_harness.investigation_reporting import export_reports


def _input():
    evidence = [{"evidence_id": "e1", "text": "Measured at 25 C.", "document_id": "doc1", "version_id": "v1", "locator": "p. 1"}]
    findings = [{"finding_id": "f1", "finding": "Measured at 25 C.", "evidence_ids": ["e1"], "value": None, "unit": None, "conditions": "25 C"}]
    claims = [{"claim_id": "c1", "claim": "Measured at 25 C.", "finding_refs": [0], "evidence_refs": ["e1"], "quote": "Measured at 25 C.", "document_id": "doc1", "version_id": "v1"}]
    sections = [{"deliverable_type": "technical_report", "language": "en", "section_id": "s1", "title": "Result", "body": "Measured at 25 C.", "claim_ids": ["c1"]}, {"deliverable_type": "technical_report", "language": "zh", "section_id": "s2", "title": "结果", "body": "在 25 C 测量。", "claim_ids": ["c1"]}]
    verification = {"status": "supported", "conclusion": "checked", "supported_claim_refs": [0]}
    spec = {"synthetic": True, "research_question": "What was measured?", "report_targets": [{"deliverable_type": "technical_report", "languages": ["en", "zh", "ja"]}]}
    return spec, evidence, findings, claims, sections, verification


def test_builds_verified_data_and_marks_real_missing_language():
    spec, evidence, findings, claims, sections, verification = _input()
    report = build_report_data("run1", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert report["validation"]["outcome"] == "partial"
    assert report["claims"][0]["verification"] == "verified"
    assert len(report["sections"]) == 2
    assert any(issue["code"] == "RH_REPORT_LANGUAGE_MISSING" and issue["language"] == "ja" for issue in report["issues"])


def test_forged_quote_and_cross_version_are_draft_and_withheld():
    spec, evidence, findings, claims, sections, verification = _input()
    claims[0]["quote"] = "invented sentence"; claims[0]["version_id"] = "v2"
    report = build_report_data("run2", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert report["validation"]["outcome"] == "partial"
    assert report["sections"] == []
    assert report["raw_model_output"]["claims"][0]["quote"] == "invented sentence"


def test_unlisted_supported_claim_and_reference_bounds_are_checked():
    spec, evidence, findings, claims, sections, verification = _input()
    verification["supported_claim_refs"] = []
    assert validate_claims(evidence, findings, claims, verification)["draft_claim_ids"] == ["c1"]
    verification["supported_claim_refs"] = [1]
    with pytest.raises(HarnessError): validate_claims(evidence, findings, claims, verification)


def test_duplicate_id_and_condition_conflict_are_rejected_or_blocked():
    spec, evidence, findings, claims, sections, verification = _input()
    with pytest.raises(HarnessError): validate_claims(evidence + [dict(evidence[0])], findings, claims, verification)
    findings.append({"finding_id": "f2", "finding": "Other condition", "evidence_ids": ["e1"], "value": None, "unit": None, "conditions": "50 C"})
    claims[0]["finding_refs"] = [0, 1]
    report = build_report_data("run4", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert any(issue["code"] == "RH_NOT_COMPARABLE" for issue in report["issues"])
    assert report["sections"] == []


def test_build_then_export_uses_runtime_synthetic_and_withheld_sections_remain_exportable(tmp_path):
    spec, evidence, findings, claims, sections, verification = _input()
    spec.pop("synthetic"); spec["runtime"] = {"data_mode": "synthetic"}; spec["report_targets"] = ["technical_report"]
    claims[0]["quote"] = "forged"
    report = build_report_data("run5", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert report["synthetic"] is True and report["validation"]["outcome"] == "partial"
    output = export_reports(tmp_path, "run5", report)
    assert output["status"] == "partial"
    assert any(item["format"] == "canonical_json" for item in output["artifacts"])


def test_partial_verification_can_support_listed_claim_but_is_overall_partial():
    spec, evidence, findings, claims, sections, verification = _input()
    verification["status"] = "partial"
    report = build_report_data("run6", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert report["claims"][0]["verification"] == "verified"
    assert report["validation"]["outcome"] == "partial"
