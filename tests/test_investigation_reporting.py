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
        "bibliography": [{"type": "article", "citation_key": "a{1}", "title": "A {title}", "author": "Doe"}],
        "coverage": {"complete": False}, "issues": [],
    }


def test_exports_different_report_types_and_languages(tmp_path):
    result = export_reports(tmp_path, "run1", _data(), languages=["en", "zh", "ja"])
    assert result["status"] == "partial"  # review/digest were not supplied in zh/ja
    paths = {item["path"] for item in result["artifacts"]}
    assert "reports/run1/v1/technical_report.en.route.md" in paths
    assert "reports/run1/v1/literature_review.en.themes.md" in paths
    assert "reports/run1/v1/patent_monitor_digest.en.changes.md" in paths
    assert (tmp_path / "reports/run1/v1/technical_report.zh.route-zh.md").read_text(encoding="utf-8").find("中文技术正文") >= 0
    assert (tmp_path / "reports/run1/v1/technical_report.ja.route-ja.md").read_text(encoding="utf-8").find("日本語の技術本文") >= 0
    assert any(item["code"] == "RH_REPORT_LANGUAGE_MISSING" and item["language"] == "ja" for item in result["issues"])


def test_escapes_html_and_neutralizes_csv_and_bibtex(tmp_path):
    data = _data()
    data["sections"][0]["title"] = "<script>alert(1)</script>"
    data["sections"][0]["body"] = "<img src=x onerror=alert(1)>"
    export_reports(tmp_path, "run2", data, languages=["en"])
    html_text = (tmp_path / "reports/run2/v1/technical_report.en.route.html").read_text(encoding="utf-8")
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
    assert canonical["report_status"] == "draft"
    assert canonical["evidence"][0]["text"] == "The measured condition was 25 C."


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
    assert "reports/run5/v1/technical_report.en.route.md" in paths
    assert "reports/run5/v1/technical_report.zh.route-zh.md" in paths
