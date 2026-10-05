"""Offline-only contract tests for integration evaluation inputs and metrics."""
from __future__ import annotations
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from research_harness.integration_evaluation import EvaluationInputError, canonical_digest, evaluate_bundle

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "integration_evaluation"

def fixture():
    case = json.loads((EXAMPLES / "case.json").read_text(encoding="utf-8"))
    runs = {name: json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8")) for name in ("rag", "paperqa", "storm")}
    return case, runs

def rehash_case(case):
    case["evidence_bundle_digest"] = "sha256:" + canonical_digest(case["evidence"])
    return case

def test_fixed_offline_bundle_metrics_are_separate_and_pending_real_comparison():
    case, runs = fixture()
    report = evaluate_bundle(case, runs)
    assert report["evaluation_rule_version"] == "integration-evaluation/2"
    assert report["fixed_evidence_count"] == 1
    for name in ("rag", "paperqa", "storm"):
        run = report["runs"][name]
        assert run["citation_metrics"]["location"] ["passed"] == 1
        assert run["citation_metrics"]["continuous_quote"]["passed"] == 1
        assert run["semantic_support"]["counts"]["not_assessed"] == 1
        assert run["semantic_support"]["counts"]["supported"] == 0
        assert run["operations"]["physical_sends"]["total"] == 0
        assert run["operations"]["cache_hits"]["total"] == 1
        assert run["operations"]["synthetic_operations"]["total"] == 1
        assert run["operations"]["fees"] is None
        assert run["recovery"]["evidence_backed_checks"] == 0
        assert run["recovery"]["checks_without_core_ledger_evidence"] == 1
    assert report["comparison"]["status"] == "pending_activation"
    assert report["comparison"]["comparison_allowed"] is False
    assert "delta" not in report["comparison"]

def test_semantic_annotation_records_four_labels_and_measured_review_time():
    case, runs = fixture()
    runs["rag"]["claims"].append({"claim_id": "rag-claim-2", "text": "another synthetic statement"})
    annotations = {"claims": [
        {"engine": "rag", "claim_id": "rag-claim-1", "label": "supported", "annotator": "reviewer-a", "source_locator": "page:1/paragraph:1", "reason": "fixture matches", "comparison_conditions": "synthetic only", "review_seconds": 12.5},
        {"engine": "rag", "claim_id": "rag-claim-2", "label": "partial", "annotator": "reviewer-a", "source_locator": "page:1/paragraph:1", "reason": "one field absent", "comparison_conditions": "synthetic only", "review_seconds": 3},
        {"engine": "paperqa", "claim_id": "paperqa-claim-1", "label": "unsupported", "annotator": "reviewer-b", "source_locator": {"kind": "page", "value": 1, "paragraph": 1}, "reason": "not entailed", "comparison_conditions": "synthetic only", "review_seconds": 0},
        {"engine": "storm", "claim_id": "storm-claim-1", "label": "contradicted", "annotator": "reviewer-c", "source_locator": "page:1/paragraph:1", "reason": "opposite value", "comparison_conditions": "synthetic only", "review_seconds": 0},
    ]}
    report = evaluate_bundle(case, runs, annotations)
    rag = report["runs"]["rag"]["semantic_support"]
    assert rag["counts"]["supported"] == 1 and rag["counts"]["partial"] == 1
    assert rag["counts"]["not_assessed"] == 0 and rag["review_seconds_measured_sum"] == 15.5
    assert report["runs"]["paperqa"]["semantic_support"]["counts"]["unsupported"] == 1
    assert report["runs"]["storm"]["semantic_support"]["counts"]["contradicted"] == 1

def test_wrong_publication_wrong_version_quote_and_missing_body_fail_independently():
    case, runs = fixture()
    for field, value in (("document_id", "different-publication"), ("version_id", "wrong-version"), ("parse_revision_id", "wrong-revision")):
        changed = copy.deepcopy(runs)
        changed["rag"]["citations"][0][field] = value
        metric = evaluate_bundle(case, changed)["runs"]["rag"]["citation_metrics"]
        assert metric["location"]["passed"] == 0
        assert metric["continuous_quote"]["passed"] == 1
    changed = copy.deepcopy(runs)
    changed["rag"]["citations"][0]["quote"] = "not in source"
    assert evaluate_bundle(case, changed)["runs"]["rag"]["citation_metrics"]["continuous_quote"]["passed"] == 0
    no_body = copy.deepcopy(case)
    no_body["evidence"][0].pop("text")
    rehash_case(no_body)
    assert evaluate_bundle(no_body, runs)["runs"]["rag"]["citation_metrics"]["continuous_quote"]["issues"][0]["code"] == "body_missing"

def test_repeated_overlapping_quote_is_ambiguous_and_duplicate_citation_id_fails_location():
    case, runs = fixture()
    case["evidence"][0]["text"] = "aaa"
    rehash_case(case)
    runs["rag"]["citations"][0]["quote"] = "aa"
    metric = evaluate_bundle(case, runs)["runs"]["rag"]["citation_metrics"]["continuous_quote"]
    assert metric["passed"] == 0 and metric["issues"][0]["match_count"] == 2
    case, runs = fixture()
    duplicate = copy.deepcopy(runs["rag"]["citations"][0])
    duplicate["claim_id"] = "rag-claim-1"
    runs["rag"]["citations"].append(duplicate)
    metric = evaluate_bundle(case, runs)["runs"]["rag"]["citation_metrics"]["location"]
    assert metric["passed"] == 0 and metric["issues"][0]["code"] == "duplicate_citation_id"

def test_unversioned_legacy_citation_requires_explicit_legacy_markers():
    case, runs = fixture()
    case["evidence"][0].pop("parse_revision_id")
    case["evidence"][0]["legacy_unversioned"] = True
    rehash_case(case)
    cite = runs["rag"]["citations"][0]
    cite.pop("parse_revision_id")
    assert evaluate_bundle(case, runs)["runs"]["rag"]["citation_metrics"]["location"]["passed"] == 0
    cite["legacy_unversioned"] = True
    assert evaluate_bundle(case, runs)["runs"]["rag"]["citation_metrics"]["location"]["passed"] == 1

def test_comparison_refuses_mismatch_and_does_not_replace_missing_real_runs():
    case, runs = fixture()
    runs["paperqa"]["comparison"]["budget"] = {"max_model_calls": 4}
    report = evaluate_bundle(case, runs)
    assert report["comparison"]["status"] == "rejected_incompatible"
    assert report["comparison"]["comparison_allowed"] is False
    case, runs = fixture()
    for name, run in runs.items():
        run["run_mode"] = "real"
        run["trace"]["calls"].append({"kind": "model", "dispatch": "physical", "outcome": "accepted", "core_call_id": f"ledger-{name}"})
    report = evaluate_bundle(case, runs)
    assert report["comparison"]["status"] == "comparable_inputs_ready_for_review"
    runs["storm"]["run_mode"] = "offline_synthetic"
    report = evaluate_bundle(case, runs)
    assert report["comparison"]["status"] == "pending_activation"

def test_coverage_source_failure_empty_success_calls_and_real_recovery_are_reported():
    case, runs = fixture()
    rag = runs["rag"]
    rag["recovery_checks"][0].update({"record_origin": "core_ledger", "core_ledger_ref": "call-ledger:check-1"})
    coverage = evaluate_bundle(case, runs)["runs"]["rag"]["coverage"]
    assert coverage["dimension_counts"]["covered"] == 1
    assert coverage["dimension_counts"]["partial"] == 1
    assert coverage["dimension_counts"]["not_assessed"] == 1
    assert coverage["source_outcomes"]["success_empty"] == 1 and coverage["source_outcomes"]["failure"] == 1
    recovery = evaluate_bundle(case, runs)["runs"]["rag"]["recovery"]
    assert recovery["evidence_backed_checks"] == recovery["matched_expected_state_checks"] == 1
    assert recovery["measured_time_ms_sum"] == 1.0 and recovery["reserved_calls_delta_sum"] == 0

def test_invalid_annotation_or_incompatible_result_set_is_rejected():
    case, runs = fixture()
    with pytest.raises(EvaluationInputError, match="unknown claim_id"):
        evaluate_bundle(case, runs, {"claims": [{"engine": "rag", "claim_id": "invented", "label": "supported"}]})
    runs.pop("storm")
    with pytest.raises(EvaluationInputError, match="exactly rag"):
        evaluate_bundle(case, runs)

def test_cli_reads_frozen_triplet_and_writes_report_without_activation():
    output = ROOT / ".local" / "integration-20261005" / "evaluation-cli-test.json"
    command = [sys.executable, str(ROOT / "scripts" / "evaluate_integration.py"),
               "--case", str(EXAMPLES / "case.json"), "--results-dir", str(EXAMPLES),
               "--annotations", str(EXAMPLES / "annotations-template.json"), "--output", str(output)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["annotation_present"] is False
    assert report["comparison"]["status"] == "pending_activation"
    output.unlink()



def test_case_digest_rejects_changed_question_or_frozen_evidence():
    case, runs = fixture()
    case["research_question"] = "changed question"
    with pytest.raises(EvaluationInputError, match="question_digest"):
        evaluate_bundle(case, runs)
    case, runs = fixture()
    case["evidence"][0]["text"] += " changed"
    with pytest.raises(EvaluationInputError, match="evidence_bundle_digest"):
        evaluate_bundle(case, runs)


def test_structured_locator_matches_canonically_and_structured_human_locator_is_valid():
    case, runs = fixture()
    locator = {"kind": "page", "value": 1, "paragraph": 1}
    case["evidence"][0]["locator"] = locator
    rehash_case(case)
    runs["rag"]["citations"][0]["locator"] = {"paragraph": 1, "value": 1, "kind": "page"}
    report = evaluate_bundle(case, runs, {"claims": [{"engine": "rag", "claim_id": "rag-claim-1",
        "label": "supported", "annotator": "reviewer", "source_locator": locator,
        "comparison_conditions": "fixture", "reason": "exact synthetic source", "review_seconds": 2.0}]})
    assert report["runs"]["rag"]["citation_metrics"]["location"]["passed"] == 1
    assert report["runs"]["rag"]["semantic_support"]["review_seconds_measured_sum"] == 2.0

def test_claims_require_ids_and_malformed_citation_ids_become_location_issues():
    case, runs = fixture()
    runs["rag"]["claims"][0].pop("claim_id")
    with pytest.raises(EvaluationInputError, match="claim_id"):
        evaluate_bundle(case, runs)
    case, runs = fixture()
    for invalid_id in (None, {}, [], 7):
        changed = copy.deepcopy(runs)
        changed["rag"]["citations"][0]["citation_id"] = invalid_id
        metric = evaluate_bundle(case, changed)["runs"]["rag"]["citation_metrics"]["location"]
        assert metric["passed"] == 0
        assert metric["issues"][0]["code"] == "citation_id_invalid"
    for invalid_id in ({"bad": "type"}, ["bad"]):
        changed = copy.deepcopy(runs)
        changed["rag"]["citations"][0]["claim_id"] = invalid_id
        metric = evaluate_bundle(case, changed)["runs"]["rag"]["citation_metrics"]["location"]
        assert metric["passed"] == 0
        assert metric["issues"][0]["code"] == "claim_id_invalid"

def test_duplicate_physical_core_call_ids_are_ambiguous_not_two_sends_or_activation_proof():
    case, runs = fixture()
    runs["rag"]["run_mode"] = "real"
    runs["rag"]["trace"]["calls"] = [
        {"kind": "model", "dispatch": "physical", "outcome": "accepted", "core_call_id": "call-1"},
        {"kind": "model", "dispatch": "physical", "outcome": "accepted", "core_call_id": "call-1"},
        {"kind": "retrieval", "dispatch": "physical", "outcome": "accepted", "physical_request_id": "request-2"},
        {"kind": "download", "dispatch": "physical", "outcome": "accepted"},
    ]
    report = evaluate_bundle(case, runs)["runs"]["rag"]["operations"]
    assert report["physical_sends"]["reported_physical_records"] == 3
    assert report["physical_sends"]["ambiguous_duplicate_records"] == 2
    assert report["physical_sends"]["unique_events_total"] == 1
    assert report["duplicate_physical_event_references"][0]["event_ref"] == "call-1"
    assert report["invalid_call_records"][0]["code"] == "physical_event_id_missing"
    assert report["accepted_physical_model_core_call_ids"] == []
