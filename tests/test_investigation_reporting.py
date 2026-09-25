import csv
import json
from pathlib import Path

import pytest

from research_harness.investigation_reporting import ReportExportError, export_reports


def _data(*, include_ja=True, bad_claim=False):
    evidence_text = "The measured condition was 25 C."
    claim = {
        "claim_id": "c1", "verification": "verified", "quote": "condition was 25 C",
        "document_id": "doc-1", "version_id": "v1", "evidence_refs": ["e1"],
    }
    if bad_claim:
        claim["version_id"] = "other-version"
    sections = [
        {"deliverable_type": "technical_report", "language": "en", "section_id": "route", "title": "Route", "body": "English technical body.", "claim_ids": ["c1"]},
        {"deliverable_type": "literature_review", "language": "en", "section_id": "themes", "title": "Themes", "body": "English review body.", "claim_ids": ["c1"]},
        {"deliverable_type": "patent_monitor_digest", "language": "en", "section_id": "changes", "title": "Changes", "body": "English monitor body.", "claim_ids": ["c1"]},
        {"deliverable_type": "technical_report", "language": "zh", "section_id": "route-zh", "title": "路线", "body": "中文技术正文。", "claim_ids": ["c1"]},
    ]
    if include_ja:
        sections.append({"deliverable_type": "technical_report", "language": "ja", "section_id": "route-ja", "title": "経路", "body": "日本語の技術本文。", "claim_ids": ["c1"]})
    return {
        "synthetic": True, "report_version": "v1", "research_question": "How does input alter output?",
        "findings": [{"finding_id": "f1", "value": "=unsafe", "unit": "m", "conditions": "@condition", "evidence_refs": ["e1"]}],
        "evidence": [{"evidence_id": "e1", "text": evidence_text, "document_id": "doc-1", "version_id": "v1", "locator": "p. 1"}],
        "claims": [claim], "sections": sections,
        "bibliography": [{"type": "article", "citation_key": "a1", "title": "A {title}", "author": "Doe"}],
        "coverage": {"complete": False}, "issues": [],
    }


def test_exports_different_report_types_and_languages(tmp_path):
    result = export_reports(tmp_path, "run1", _data(), languages=["en", "zh", "ja"])
    assert result["status"] == "partial"  # review/digest were not supplied in zh/ja
    paths = {item["path"] for item in result["artifacts"]}
    assert "reports/run1/v1/technical_report.en.md" in paths
    assert "reports/run1/v1/literature_review.en.md" in paths
    assert "reports/run1/v1/patent_monitor_digest.en.md" in paths
    assert (tmp_path / "reports/run1/v1/technical_report.zh.md").read_text(encoding="utf-8").find("中文技术正文") >= 0
    assert (tmp_path / "reports/run1/v1/technical_report.ja.md").read_text(encoding="utf-8").find("日本語の技術本文") >= 0
    assert any(item["code"] == "RH_REPORT_LANGUAGE_MISSING" and item["language"] == "ja" for item in result["issues"])


def test_escapes_html_and_neutralizes_csv_and_bibtex(tmp_path):
    data = _data()
    data["sections"][0]["title"] = "<script>alert(1)</script>"
    data["sections"][0]["body"] = "<img src=x onerror=alert(1)>"
    export_reports(tmp_path, "run2", data, languages=["en"])
    html_text = (tmp_path / "reports/run2/v1/technical_report.en.html").read_text(encoding="utf-8")
    assert "<script>" not in html_text and "&lt;script&gt;" in html_text
    with (tmp_path / "reports/run2/v1/comparison.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[1][1] == "'=unsafe" and rows[1][3] == "'@condition"
    assert "\\{" in (tmp_path / "reports/run2/v1/bibliography.bib").read_text(encoding="utf-8")


def test_invalid_document_version_never_enters_body_and_canonical_is_retryable(tmp_path):
    result = export_reports(tmp_path, "run3", _data(bad_claim=True), languages=["en"])
    assert result["status"] == "partial"
    assert any(issue["code"] == "RH_REPORT_CITATION_INVALID" for issue in result["issues"])
    assert not (tmp_path / "reports/run3/v1/technical_report.en.route.md").exists()
    canonical = json.loads((tmp_path / "reports/run3/v1/report-data.canonical.json").read_text(encoding="utf-8"))
    assert canonical["kind"] == "frozen_report_data"
    assert canonical["report_data"]["evidence"][0]["text"] == "The measured condition was 25 C."


def test_idempotence_conflict_and_workspace_boundary(tmp_path):
    data = _data()
    first = export_reports(tmp_path, "run4", data, languages=["en"])
    second = export_reports(tmp_path, "run4", data, languages=["en"])
    assert first == second
    changed = _data()
    changed["sections"][0]["body"] = "Different factual body."
    with pytest.raises(ReportExportError):
        export_reports(tmp_path, "run4", changed, languages=["en"])
    with pytest.raises(Exception):
        export_reports(tmp_path, "../escape", data, languages=["en"])


def test_same_frozen_facts_can_add_a_language_without_losing_prior_artifacts(tmp_path):
    data = _data()
    export_reports(tmp_path, "run5", data, languages=["en"])
    extended = export_reports(tmp_path, "run5", data, languages=["zh"])
    paths = {item["path"] for item in extended["artifacts"]}
    assert "reports/run5/v1/technical_report.en.md" in paths
    assert "reports/run5/v1/technical_report.zh.md" in paths


def test_explicit_targets_create_complete_traceable_synthetic_report(tmp_path):
    data = _data()
    data["report_targets"] = [{"deliverable_type": "technical_report", "languages": ["en"]}]
    result = export_reports(tmp_path, "run6", data)
    assert result["status"] == "completed"
    text = (tmp_path / "reports/run6/v1/technical_report.en.md").read_text(encoding="utf-8")
    assert "SYNTHETIC REPORT" in text
    assert "evidence `e1`" in text and "document `doc-1`" in text and "locator `p. 1`" in text


def test_rejects_empty_scientific_claims_duplicate_ids_and_unsafe_language(tmp_path):
    no_claim = _data()
    no_claim["report_targets"] = [{"deliverable_type": "technical_report", "languages": ["en"]}]
    no_claim["sections"][0]["claim_ids"] = []
    result = export_reports(tmp_path, "run7", no_claim)
    assert result["status"] == "partial"
    assert not (tmp_path / "reports/run7/v1/technical_report.en.md").exists()
    duplicate = _data(); duplicate["evidence"].append(dict(duplicate["evidence"][0]))
    with pytest.raises(Exception): export_reports(tmp_path, "run8", duplicate, languages=["en"])
    with pytest.raises(Exception): export_reports(tmp_path, "run9", _data(), languages=["../escape"])


def test_corrupt_artifact_is_rebuilt_from_frozen_data(tmp_path):
    data = _data(); data["report_targets"] = [{"deliverable_type": "technical_report", "languages": ["en"]}]
    export_reports(tmp_path, "run10", data)
    path = tmp_path / "reports/run10/v1/technical_report.en.md"
    path.write_text("corrupt", encoding="utf-8")
    export_reports(tmp_path, "run10", data)
    assert "English technical body." in path.read_text(encoding="utf-8")


def test_bibtex_rejects_duplicate_keys_and_unknown_fields(tmp_path):
    duplicate = _data()
    duplicate["bibliography"].append(dict(duplicate["bibliography"][0], title="Second"))
    with pytest.raises(Exception): export_reports(tmp_path, "run11", duplicate, languages=["en"])
    unknown = _data(); unknown["bibliography"][0]["custom_field"] = "unsupported"
    with pytest.raises(Exception): export_reports(tmp_path, "run12", unknown, languages=["en"])


def test_baseline_visibility_is_retained_in_canonical_data_but_omitted_from_bibtex(tmp_path):
    data = _data()
    data["evidence"][0].update(document_id="baseline-doc", version_id="baseline-v1")
    data["claims"][0].update(document_id="baseline-doc", version_id="baseline-v1")
    data["bibliography"] = [{
        "id": "baseline-doc", "type": "article", "title": "Baseline source",
        "doi": "10.1000/baseline", "visibility": "public",
    }]
    export_reports(tmp_path, "run-baseline", data, languages=["en"])
    root = tmp_path / "reports/run-baseline/v1"
    canonical = json.loads((root / "report-data.canonical.json").read_text(encoding="utf-8"))
    assert canonical["report_data"]["bibliography"][0]["visibility"] == "public"
    bibliography = (root / "bibliography.bib").read_text(encoding="utf-8")
    assert "visibility" not in bibliography and "doi = {10.1000/baseline}" in bibliography


def test_bibtex_projects_review_as_article_but_preserves_canonical_type(tmp_path):
    data = _data()
    data["bibliography"] = [{"id": "review-doc", "type": "review", "title": "Review source"}]
    export_reports(tmp_path, "run-review", data, languages=["en"])
    root = tmp_path / "reports/run-review/v1"
    canonical = json.loads((root / "report-data.canonical.json").read_text(encoding="utf-8"))
    assert canonical["report_data"]["bibliography"][0]["type"] == "review"
    assert "@article{review-doc," in (root / "bibliography.bib").read_text(encoding="utf-8")
    data["bibliography"][0]["type"] = "dataset"
    with pytest.raises(Exception):
        export_reports(tmp_path, "run-unknown-type", data, languages=["en"])


def test_bibtex_generates_stable_safe_key_for_doi_with_slash(tmp_path):
    data = _data()
    data["bibliography"] = [{"type": "article", "title": "DOI source", "doi": "10.1039/d0ee01133a"}]
    export_reports(tmp_path, "run13", data, languages=["en"])
    text = (tmp_path / "reports/run13/v1/bibliography.bib").read_text(encoding="utf-8")
    assert "@article{ref" in text and "doi = {10.1039/d0ee01133a}" in text


def test_bibtex_keeps_safe_fallback_id_as_key(tmp_path):
    data = _data()
    data["bibliography"] = [{"type": "misc", "title": "Identifier source", "id": "reference17"}]
    export_reports(tmp_path, "run14", data, languages=["en"])
    assert "@misc{reference17," in (tmp_path / "reports/run14/v1/bibliography.bib").read_text(encoding="utf-8")


def test_bibtex_projects_patent_publication_without_inventing_doi(tmp_path):
    data = _data()
    data["bibliography"] = [{"type": "patent", "title": "Patent source", "id": "WO2026182370A1", "publication_id": "WO2026182370A1"}]
    export_reports(tmp_path, "run-patent", data, languages=["en"])
    root = tmp_path / "reports/run-patent/v1"
    canonical = json.loads((root / "report-data.canonical.json").read_text(encoding="utf-8"))
    assert canonical["report_data"]["bibliography"][0]["type"] == "patent"
    bib = (root / "bibliography.bib").read_text(encoding="utf-8")
    assert "@misc{WO2026182370A1," in bib and "note = {Patent publication WO2026182370A1}" in bib
    assert "doi" not in bib.lower()


def test_bibtex_projects_frozen_paper_type_as_article(tmp_path):
    data = _data()
    data["bibliography"] = [{"type": "paper", "title": "Paper source", "id": "paper-1"}]
    export_reports(tmp_path, "run-paper", data, languages=["en"])
    root = tmp_path / "reports/run-paper/v1"
    canonical = json.loads((root / "report-data.canonical.json").read_text(encoding="utf-8"))
    assert canonical["report_data"]["bibliography"][0]["type"] == "paper"
    assert "@article{paper-1," in (root / "bibliography.bib").read_text(encoding="utf-8")
