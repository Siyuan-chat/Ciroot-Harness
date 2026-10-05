import pytest

from research_harness.errors import HarnessError
from research_harness.investigation_report_data import _language_hint, build_report_data, validate_claims
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
    assert report["report_contract_version"] == "report-block-v2"
    assert report["sections"][0]["body"] == claims[0]["claim"]
    assert report["sections"][0]["blocks"] == [{"block_id": "s1:fact:c1", "kind": "fact", "claim_id": "c1", "text": claims[0]["claim"]}]
    assert report["claims"][0]["report_checks"]["quote_match"] == "matched"
    assert report["claims"][0]["report_checks"]["quote_match_note"].startswith("substring match")
    assert any(issue["code"] == "RH_REPORT_LANGUAGE_UNVERIFIED" and issue["source_language_hint"] == "en" for issue in report["issues"])


def test_free_prose_is_diagnostic_and_context_sections_cannot_bypass_claims():
    spec, evidence, findings, claims, sections, verification = _input()
    sections[0]["body"] += " This route is mass-production ready and reduces cost by 50%."
    sections[0]["section_kind"] = "context"
    sections.append({"deliverable_type": "technical_report", "language": "en", "section_id": "method",
                     "section_kind": "method", "title": "Method", "body": "A safe method was proven.", "claim_ids": []})
    report = build_report_data("run-draft", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert len(report["sections"]) == 1
    assert all(section["section_id"] != "method" for section in report["sections"])
    assert all("mass-production ready" not in section["body"] for section in report["sections"])
    assert report["raw_model_output"]["sections"][0]["body"].endswith("reduces cost by 50%.")
    assert any(issue["code"] == "RH_SECTION_KIND_DRAFT" and issue.get("section_id") == "s1" for issue in report["issues"])
    assert any(issue["code"] == "RH_SECTION_DRAFT" and issue.get("section_id") == "method" for issue in report["issues"])


def test_claim_self_reported_verified_cannot_bypass_independent_verification():
    spec, evidence, findings, claims, sections, verification = _input()
    claims[0]["verification"] = "verified"
    verification["status"] = "insufficient"
    verification["supported_claim_refs"] = []
    report = build_report_data("run-unverified", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert report["claims"][0]["verification"] == "draft"
    assert report["claims"][0]["report_checks"]["independent_verifier"] == "not_accepted"
    assert report["sections"] == []


def test_new_report_export_uses_only_accepted_blocks_and_rejects_tampering(tmp_path):
    spec, evidence, findings, claims, sections, verification = _input()
    sections[0]["body"] += " This route is mass-production ready and reduces cost by 50%."
    spec["report_targets"] = [{"deliverable_type": "technical_report", "languages": ["en"]}]
    report = build_report_data("run-blocks", spec, evidence, findings, claims, sections, verification, [], {}, [])
    exported = export_reports(tmp_path, "run-blocks", report, languages=["en"])
    markdown = (tmp_path / "reports/run-blocks/v1/technical_report.en.md").read_text(encoding="utf-8")
    assert claims[0]["claim"] in markdown
    assert "mass-production ready" not in markdown
    assert exported["status"] == "partial"

    changed = {**report, "sections": [dict(report["sections"][0], body="Injected factual rewrite.")]}
    with pytest.raises(HarnessError):
        export_reports(tmp_path, "run-blocks-tampered", changed, languages=["en"])

    changed_section = dict(report["sections"][0])
    changed_section["blocks"] = [dict(changed_section["blocks"][0], kind="method")]
    changed = {**report, "sections": [changed_section]}
    with pytest.raises(HarnessError):
        export_reports(tmp_path, "run-block-kind-tampered", changed, languages=["en"])

    changed_section = dict(report["sections"][0])
    changed_section["blocks"] = [dict(changed_section["blocks"][0], claim_id="forged")]
    changed = {**report, "sections": [changed_section]}
    with pytest.raises(HarnessError):
        export_reports(tmp_path, "run-block-binding-tampered", changed, languages=["en"])


def test_report_block_kinds_require_accepted_claims_and_gap_is_core_projected():
    spec, evidence, findings, claims, sections, verification = _input()
    sections[0]["section_kind"] = "explanation"
    sections[0]["body"] = "A verified interpretation."
    sections.append({"deliverable_type": "technical_report", "language": "en", "section_id": "free-gap",
                     "section_kind": "gap", "title": "Gap", "body": "Invented limitation.", "claim_ids": ["c1"]})
    issue = {"code": "RH_SOURCE_MISSING", "message": "Sensitive user supplied prose must never be projected."}
    report = build_report_data("run-kinds", spec, evidence, findings, claims, sections, verification, [],
                               {"complete": False}, [issue])
    assert report["sections"][0]["blocks"][0]["kind"] == "explanation"
    assert report["sections"][0]["blocks"][0]["claim_id"] == "c1"
    gap = report["sections"][0]["blocks"][-1]
    assert gap["kind"] == "gap"
    assert gap["issue_refs"] == ["RH_SOURCE_MISSING"]
    assert gap["coverage_refs"] == ["coverage.complete"]
    assert "Sensitive user supplied prose" not in gap["text"]
    assert all(section["section_id"] != "free-gap" for section in report["sections"])
    assert any(item["code"] == "RH_SECTION_KIND_DRAFT" and item.get("section_id") == "free-gap" for item in report["issues"])


def test_report_block_v1_frozen_export_remains_readable(tmp_path):
    spec, evidence, findings, claims, sections, verification = _input()
    report = build_report_data("run-v1-source", spec, evidence, findings, claims, sections[:1], verification, [], {}, [])
    # Reconstitute the frozen v1 shape without changing any underlying claim data.
    report.pop("report_contract_version")
    report["report_contract"] = "report-block-v1"
    report.pop("report_contract_sources")
    section = report["sections"][0]
    section.pop("section_kind", None)
    section["blocks"] = [{"block_id": "s1:c1", "kind": "accepted_claim", "claim_id": "c1", "text": claims[0]["claim"]}]
    report["sections"] = [section]
    export_reports(tmp_path, "run-v1-frozen", report, languages=["en"])


def test_reported_translation_is_explicitly_rendered_in_claim_source_language(tmp_path):
    spec, evidence, findings, claims, sections, verification = _input()
    spec["report_targets"] = [{"deliverable_type": "technical_report", "languages": ["zh"]}]
    report = build_report_data("run-language", spec, evidence, findings, claims, sections, verification, [], {}, [])
    result = export_reports(tmp_path, "run-language", report, languages=["zh"])
    markdown_path = tmp_path / "reports/run-language/v1/technical_report.zh.md"
    html_path = tmp_path / "reports/run-language/v1/technical_report.zh.html"
    markdown = markdown_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")
    assert result["status"] == "partial"
    assert "原文语言启发式提示：en" in markdown
    assert "lang=\"en\"" in html
    assert any(issue["code"] == "RH_REPORT_LANGUAGE_UNVERIFIED" for issue in result["issues"])


def test_untrusted_section_title_is_diagnostic_and_never_rendered(tmp_path):
    spec, evidence, findings, claims, sections, verification = _input()
    sections[0]["title"] = "Result; mass production ready; costs reduced 50%"
    spec["report_targets"] = [{"deliverable_type": "technical_report", "languages": ["en"]}]
    report = build_report_data("run-title", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert report["sections"][0]["title"] == "Verified claims"
    assert report["raw_model_output"]["sections"][0]["title"] == sections[0]["title"]
    assert any(issue["code"] == "RH_SECTION_TITLE_DRAFT" for issue in report["issues"])
    export_reports(tmp_path, "run-title", report, languages=["en"])
    markdown = (tmp_path / "reports/run-title/v1/technical_report.en.md").read_text(encoding="utf-8")
    html = (tmp_path / "reports/run-title/v1/technical_report.en.html").read_text(encoding="utf-8")
    assert "costs reduced 50%" not in markdown and "costs reduced 50%" not in html


def test_language_hint_is_conservative_for_hangul_han_and_mixed_text():
    assert _language_hint("검증 결과 25%") == "ko"
    assert _language_hint("測定値") == "und"
    assert _language_hint("Cost 25% 測定") == "mixed"
    assert _language_hint("経路を測定") == "ja"
    assert _language_hint("검증 25 kPa") == "mixed"


def test_empty_or_unbound_claim_references_fail_each_provenance_check():
    spec, evidence, findings, claims, sections, verification = _input()
    claims[0]["evidence_refs"] = []
    report = build_report_data("run-empty-refs", spec, evidence, findings, claims, sections, verification, [], {}, [])
    checks = report["claims"][0]["report_checks"]
    assert checks["identity"] == checks["locator"] == "fail"
    assert checks["quote_match"] == "unmatched"
    assert checks["finding_binding"] == "fail"

    spec, evidence, findings, claims, sections, verification = _input()
    findings.append({"finding_id": "f2", "finding": "Other", "evidence_ids": ["e2"], "value": None, "unit": None, "conditions": None})
    evidence.append({"evidence_id": "e2", "text": "Other", "document_id": "doc1", "version_id": "v1", "locator": "p. 2"})
    claims[0]["finding_refs"] = [1]
    report = build_report_data("run-unbound", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert report["claims"][0]["report_checks"]["finding_binding"] == "fail"


def test_parse_revision_is_required_for_new_evidence_and_rechecked_on_export(tmp_path):
    spec, evidence, findings, claims, sections, verification = _input()
    evidence[0]["parse_revision_id"] = "pr-current"
    claims[0]["parse_revision_id"] = "pr-current"
    report = build_report_data("run-revision", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert report["claims"][0]["verification"] == "verified"
    assert report["claims"][0]["report_checks"]["parse_revision"] == "pass"
    assert report["sections"]

    claims[0].pop("parse_revision_id")
    missing = build_report_data("run-revision-missing", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert missing["claims"][0]["verification"] == "draft"
    assert missing["claims"][0]["report_checks"]["parse_revision"] == "fail"
    assert missing["sections"] == []

    claims[0]["parse_revision_id"] = "pr-old"
    wrong = build_report_data("run-revision-wrong", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert wrong["claims"][0]["verification"] == "draft"
    assert wrong["claims"][0]["report_checks"]["parse_revision"] == "fail"

    claims[0]["parse_revision_id"] = "pr-current"
    frozen = build_report_data("run-revision-export", spec, evidence, findings, claims, sections, verification, [], {}, [])
    tampered = {**frozen, "evidence": [dict(evidence[0], parse_revision_id="pr-changed")]}
    with pytest.raises(HarnessError):
        export_reports(tmp_path, "run-revision-export", tampered, languages=["en"])


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

def test_string_target_and_empty_supported_facts_cannot_complete_report():
    spec, evidence, findings, claims, sections, verification = _input()
    spec["report_targets"] = ["literature_review"]
    report = build_report_data("run7", spec, evidence, findings, claims, sections, verification, [], {}, [])
    assert report["validation"]["outcome"] == "partial"
    assert any(issue["code"] == "RH_REPORT_BODY_MISSING" for issue in report["issues"])
    report = build_report_data("run8", {**spec, "report_targets": ["technical_report"]}, [], [], [], [], {"status": "supported", "conclusion": "checked", "supported_claim_refs": []}, [], {}, [])
    assert any(issue["code"] == "RH_REPORT_NO_SUPPORTED_EVIDENCE" for issue in report["issues"])
