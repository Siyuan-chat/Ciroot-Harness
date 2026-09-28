import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from research_harness.golden_demo import run_golden_demo
from research_harness.investigation import InvestigationError, InvestigationService


ROOT = Path(__file__).parents[1]


def test_golden_scenario_json_is_unambiguous():
    def reject_duplicate_keys(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out

    path = ROOT / "src" / "research_harness" / "examples" / "investigation" / "golden-demo-scenario.json"
    scenario = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=reject_duplicate_keys)
    gap = next(item for item in scenario["sources"] if item["document_id"] == "paper-review-gap")
    assert gap["content_type"] == "application/xml"
    assert gap["text"] == "<broken"


def test_golden_demo_runs_service_and_reopens(tmp_path):
    outcome = run_golden_demo(str(tmp_path))
    assert outcome["synthetic"] is True
    assert outcome["outcome"] == "partial"
    assert outcome["candidate_count"] == 3
    assert outcome["evidence_document_count"] == 2
    assert outcome["verified_claim_count"] >= 2
    assert outcome["open_issue_count"] >= 1
    assert len(outcome["coverage"]["queries"]) >= 2
    assert len(outcome["coverage"]["attempts"]) >= 2
    run_id = outcome["run_id"]
    service = InvestigationService(str(tmp_path))
    try:
        frozen_spec = json.loads(service.db.execute("SELECT spec FROM investigations WHERE id=?", (run_id,)).fetchone()["spec"])
        assert frozen_spec["research_question"] == "Compare synthetic membrane routes."
        result = service.get_result(run_id)
        assert result["outcome"] == "partial"
        assert any(issue.get("code") == "RH_NORMALIZE_XML" and issue.get("status") == "open" for issue in result["issues"])
        report = service.build_report_data(run_id)
        assert report["synthetic"] is True
        assert len(report["claims"]) >= 2
        evidence_by_id = {item["evidence_id"]: item for item in report["evidence"]}
        verified_claims = [claim for claim in report["claims"] if claim.get("verification") == "verified"]
        assert len(verified_claims) >= 2
        for claim in verified_claims:
            assert claim["evidence_refs"]
            source = evidence_by_id[claim["evidence_refs"][0]]
            assert (claim["document_id"], claim["version_id"]) == (source["document_id"], source["version_id"])
            assert claim["quote"] in source["text"]
            assert source["locator"] and source["text"]
        assert all(item.get("evidence_id") and item.get("document_id") and item.get("version_id") and item.get("locator") and item.get("text") for item in report["evidence"] if item["document_id"] != "paper-review-gap")
        exported = service.export_report(run_id, ["en"])
        kinds = {item["type"] for item in exported["artifacts"]}
        assert {"technical_report", "literature_review"} <= kinds
        assert all((tmp_path / item["path"]).is_file() for item in exported["artifacts"])
        markdown = {item["type"]: (tmp_path / item["path"]).read_text(encoding="utf-8") for item in exported["artifacts"] if item.get("format") == "markdown"}
        assert set(markdown) >= {"technical_report", "literature_review"}
        for kind in ("technical_report", "literature_review"):
            assert "SYNTHETIC REPORT" in markdown[kind]
            assert any(claim["claim"] in markdown[kind] and claim["quote"] in markdown[kind] for claim in verified_claims)
            assert any(evidence_id in markdown[kind] and item["document_id"] in markdown[kind] and item["version_id"] in markdown[kind] and str(item["locator"]) in markdown[kind] for evidence_id, item in evidence_by_id.items() if item["document_id"] != "paper-review-gap")
        for item in exported["artifacts"]:
            if item["type"] in {"technical_report", "literature_review"} and item.get("format") == "markdown":
                assert "SYNTHETIC REPORT" in (tmp_path / item["path"]).read_text(encoding="utf-8")
    finally:
        service.close()


def test_golden_demo_cli_smoke(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    command = [sys.executable, "-m", "research_harness.cli", "investigate", "--workspace", str(tmp_path), "golden-demo"]
    completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["run_id"].startswith("inv-")
    assert payload["outcome"] == "partial"
    assert payload["candidate_count"] == 3
    assert payload["evidence_document_count"] == 2
    assert payload["verified_claim_count"] >= 2
    reopened = subprocess.run([sys.executable, "-m", "research_harness.cli", "investigate", "--workspace", str(tmp_path), "result", payload["run_id"]], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert reopened.returncode == 0, reopened.stderr
    assert json.loads(reopened.stdout)["synthetic"] is True
    exported = subprocess.run([sys.executable, "-m", "research_harness.cli", "investigate", "--workspace", str(tmp_path), "report", payload["run_id"], "--languages", "en"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert exported.returncode == 0, exported.stderr
    types = {item["type"] for item in json.loads(exported.stdout)["artifacts"]}
    assert {"technical_report", "literature_review"} <= types


def test_golden_demo_reports_stalled_run(monkeypatch, tmp_path):
    monkeypatch.setattr(InvestigationService, "get_pending_tasks", lambda self, run_id: [])
    service = InvestigationService(str(tmp_path))
    try:
        with pytest.raises(InvestigationError) as error:
            run_golden_demo(str(tmp_path), service)
        assert error.value.code == "RH_GOLDEN_DEMO_STALLED"
    finally:
        service.close()
