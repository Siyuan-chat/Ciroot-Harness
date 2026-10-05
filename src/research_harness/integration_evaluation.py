"""Offline metrics for fixed, frozen research-engine result bundles."""
from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections import Counter
from typing import Any

RULE_VERSION = "integration-evaluation/2"
CASE_DIGEST_RULE = "canonical-json-frozen-evidence-and-utf8-question-sha256/1"
QUOTE_RULE = "unicode-nfc-whitespace-collapse-case-sensitive-overlap-aware/1"
ENGINES = ("rag", "paperqa", "storm")
SEMANTIC_LABELS = ("supported", "partial", "unsupported", "contradicted")
SEMANTIC_STATES = (*SEMANTIC_LABELS, "not_assessed")
CALL_KINDS = ("model", "embedding", "retrieval", "source_query", "download", "metadata")
RECOVERY_TYPES = ("reopen", "duplicate_click", "late_response", "unknown_result")


class EvaluationInputError(ValueError):
    """Input is malformed or violates the frozen evaluation contract."""


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def _overlapping_occurrences(text: str, quote: str) -> int:
    if not quote:
        return 0
    count, start = 0, 0
    while True:
        index = text.find(quote, start)
        if index < 0:
            return count
        count += 1
        start = index + 1


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _case_evidence(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    evidence = case.get("evidence")
    if not isinstance(evidence, list):
        raise EvaluationInputError("case.evidence must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if not isinstance(item, dict) or not _nonempty_string(item.get("evidence_id")):
            raise EvaluationInputError("each frozen evidence item needs evidence_id")
        key = item["evidence_id"]
        if key in by_id:
            raise EvaluationInputError(f"duplicate frozen evidence_id: {key}")
        by_id[key] = item
    return by_id


def _valid_locator(value: Any) -> bool:
    if _nonempty_string(value):
        return True
    if isinstance(value, (dict, list)) and value:
        try:
            canonical_digest(value)
            return True
        except (TypeError, ValueError):
            return False
    return False


def _locator_equal(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    if not _valid_locator(left) or not _valid_locator(right):
        return False
    try:
        return canonical_digest(left) == canonical_digest(right)
    except (TypeError, ValueError):
        return False


def _exact_location(citation: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str | None]:
    for field in ("document_id", "version_id"):
        if not _nonempty_string(evidence.get(field)) or citation.get(field) != evidence.get(field):
            return False, field
    if not _valid_locator(evidence.get("locator")) or not _locator_equal(citation.get("locator"), evidence.get("locator")):
        return False, "locator"
    case_revision = evidence.get("parse_revision_id")
    cite_revision = citation.get("parse_revision_id")
    if case_revision is None:
        if evidence.get("legacy_unversioned") is not True or citation.get("legacy_unversioned") is not True or cite_revision is not None:
            return False, "parse_revision_id"
    elif not _nonempty_string(case_revision) or cite_revision != case_revision:
        return False, "parse_revision_id"
    return True, None


def _validated_claim_ids(claims: list[Any], engine: str) -> set[str]:
    ids: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict) or not _nonempty_string(claim.get("claim_id")):
            raise EvaluationInputError(f"{engine}: claim at index {index} needs a non-empty string claim_id")
        claim_id = claim["claim_id"]
        if claim_id in ids:
            raise EvaluationInputError(f"{engine}: duplicate claim_id: {claim_id}")
        ids.add(claim_id)
    return ids


def _citation_metrics(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    by_evidence = _case_evidence(case)
    claims = run.get("claims", [])
    citations = run.get("citations", [])
    if not isinstance(claims, list) or not isinstance(citations, list):
        raise EvaluationInputError(f"{run.get('engine')}: claims and citations must be lists")
    known_claims = _validated_claim_ids(claims, str(run.get("engine")))
    seen_citation_ids: set[str] = set()
    duplicates: set[str] = set()
    for item in citations:
        if isinstance(item, dict) and _nonempty_string(item.get("citation_id")):
            cid = item["citation_id"]
            if cid in seen_citation_ids:
                duplicates.add(cid)
            seen_citation_ids.add(cid)
    location_pass, quote_pass = 0, 0
    location_issues: list[dict[str, Any]] = []
    quote_issues: list[dict[str, Any]] = []
    for index, citation in enumerate(citations):
        if not isinstance(citation, dict):
            location_issues.append({"citation_index": index, "code": "invalid_citation"})
            quote_issues.append({"citation_index": index, "code": "invalid_citation"})
            continue
        cid = citation.get("citation_id")
        ref = {"citation_id": cid} if _nonempty_string(cid) else {"citation_index": index}
        if not _nonempty_string(cid):
            location_issues.append({**ref, "code": "citation_id_invalid"})
        elif cid in duplicates:
            location_issues.append({**ref, "code": "duplicate_citation_id"})
        else:
            claim_id = citation.get("claim_id")
            if not _nonempty_string(claim_id):
                location_issues.append({**ref, "code": "claim_id_invalid"})
            elif claim_id not in known_claims:
                location_issues.append({**ref, "code": "unknown_claim"})
            else:
                evidence_id = citation.get("evidence_id")
                evidence = by_evidence.get(evidence_id) if isinstance(evidence_id, str) else None
                if evidence is None:
                    location_issues.append({**ref, "code": "evidence_missing"})
                else:
                    ok, field = _exact_location(citation, evidence)
                    if ok:
                        location_pass += 1
                    else:
                        location_issues.append({**ref, "code": "identity_mismatch", "field": field})
        evidence_id = citation.get("evidence_id")
        evidence = by_evidence.get(evidence_id) if isinstance(evidence_id, str) else None
        quote = citation.get("quote")
        body = evidence.get("text") if evidence else None
        if not _nonempty_string(quote):
            quote_issues.append({**ref, "code": "quote_missing"})
        elif not _nonempty_string(body):
            quote_issues.append({**ref, "code": "body_missing"})
        else:
            normalized_quote, normalized_body = _norm(quote), _norm(body)
            matches = _overlapping_occurrences(normalized_body, normalized_quote)
            if matches == 1:
                quote_pass += 1
            else:
                quote_issues.append({**ref, "code": "quote_not_unique_contiguous", "match_count": matches})
    denominator = len(citations)
    return {
        "location": {"passed": location_pass, "denominator": denominator,
                     "ratio": location_pass / denominator if denominator else None,
                     "rule_version": "evidence-id-document-version-parse-revision-canonical-locator-exact/2",
                     "legacy_unversioned_allowed_only_when-explicit": True, "issues": location_issues},
        "continuous_quote": {"passed": quote_pass, "denominator": denominator,
                     "ratio": quote_pass / denominator if denominator else None,
                     "rule_version": QUOTE_RULE, "issues": quote_issues},
    }


def _semantic_metrics(run: dict[str, Any], annotations: dict[str, Any] | None) -> dict[str, Any]:
    claims = run.get("claims", [])
    ids = _validated_claim_ids(claims, str(run.get("engine")))
    labels: dict[str, dict[str, Any]] = {}
    if annotations is not None:
        rows = annotations.get("claims", [])
        if not isinstance(rows, list):
            raise EvaluationInputError("annotations.claims must be a list")
        for row in rows:
            if not isinstance(row, dict) or row.get("engine") not in ENGINES:
                raise EvaluationInputError("each annotation needs a known engine name")
            if row.get("engine") != run.get("engine"):
                continue
            claim_id, label = row.get("claim_id"), row.get("label")
            if not _nonempty_string(claim_id):
                raise EvaluationInputError("annotation claim_id must be a non-empty string")
            if claim_id not in ids:
                raise EvaluationInputError(f"annotation refers to unknown claim_id: {claim_id}")
            if label is None or label == "":
                continue
            if label not in SEMANTIC_LABELS:
                raise EvaluationInputError("annotated labels must be supported, partial, unsupported, or contradicted")
            for field in ("annotator", "comparison_conditions", "reason"):
                if not _nonempty_string(row.get(field)):
                    raise EvaluationInputError(f"annotated claim needs {field}")
            if not _valid_locator(row.get("source_locator")):
                raise EvaluationInputError("annotated claim needs a non-empty string or structured source_locator")
            duration = row.get("review_seconds")
            if (isinstance(duration, bool) or not isinstance(duration, (int, float)) or
                    not math.isfinite(duration) or duration < 0):
                raise EvaluationInputError("annotated claim needs measured non-negative review_seconds")
            if claim_id in labels:
                raise EvaluationInputError(f"duplicate annotation for claim_id: {claim_id}")
            labels[claim_id] = row
    counts = Counter(labels.get(claim_id, {}).get("label", "not_assessed") for claim_id in ids)
    reviewed = [row["review_seconds"] for row in labels.values() if isinstance(row.get("review_seconds"), (int, float)) and not isinstance(row.get("review_seconds"), bool) and math.isfinite(row["review_seconds"]) and row["review_seconds"] >= 0]
    return {"counts": {key: counts[key] for key in SEMANTIC_STATES},
            "denominator": len(ids), "annotated": len(labels), "unassessed": counts["not_assessed"],
            "rule_version": "human-label-per-claim/no-unmarked-supported/1",
            "review_seconds_measured_sum": sum(reviewed) if reviewed else None,
            "reviewed_claims_with_time": len(reviewed),
            "unannotated_claim_ids": sorted(ids - set(labels))}


def _coverage_metrics(case: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("dimensions", [])
    observed = run.get("coverage", {}).get("dimensions", []) if isinstance(run.get("coverage"), dict) else []
    if not isinstance(expected, list) or not all(_nonempty_string(x) for x in expected) or len(set(expected)) != len(expected):
        raise EvaluationInputError("case.dimensions must be unique non-empty strings")
    if not isinstance(observed, list):
        raise EvaluationInputError("run.coverage.dimensions must be a list")
    states = {"covered", "partial", "missing", "not_assessed"}
    by_id: dict[str, str] = {}
    for row in observed:
        if not isinstance(row, dict) or row.get("dimension_id") not in expected or row.get("status") not in states or row["dimension_id"] in by_id:
            raise EvaluationInputError(f"{run.get('engine')}: invalid or duplicate coverage dimension")
        by_id[row["dimension_id"]] = row["status"]
    dimensions = {item: by_id.get(item, "not_assessed") for item in expected}
    dimension_counts = Counter(dimensions.values())
    outcomes = run.get("source_outcomes", [])
    if not isinstance(outcomes, list):
        raise EvaluationInputError("run.source_outcomes must be a list")
    source_counts = Counter()
    for item in outcomes:
        if not isinstance(item, dict) or item.get("status") not in {"success_empty", "success_with_results", "failure", "pending"}:
            raise EvaluationInputError("source outcome status must be success_empty, success_with_results, failure, or pending")
        source_counts[item["status"]] += 1
    gaps = run.get("coverage", {}).get("gaps", []) if isinstance(run.get("coverage"), dict) else []
    if not isinstance(gaps, list):
        raise EvaluationInputError("coverage.gaps must be a list")
    return {"dimensions": dimensions,
            "dimension_counts": {key: dimension_counts[key] for key in sorted(states)},
            "dimension_denominator": len(expected),
            "source_outcomes": {key: source_counts[key] for key in ("success_with_results", "success_empty", "failure", "pending")},
            "source_outcome_denominator": len(outcomes), "coverage_gaps": gaps,
            "rule_version": "case-fixed-dimensions-and-explicit-source-outcomes/1"}


def _operations_metrics(run: dict[str, Any]) -> dict[str, Any]:
    trace = run.get("trace", {})
    calls = trace.get("calls", []) if isinstance(trace, dict) else None
    if not isinstance(calls, list):
        raise EvaluationInputError("run.trace.calls must be a list")
    cache, synthetic, physical = Counter(), Counter(), Counter()
    invalid, physical_refs = [], {}
    for index, call in enumerate(calls):
        if not isinstance(call, dict) or call.get("kind") not in CALL_KINDS or call.get("dispatch") not in {"physical", "cache_hit", "synthetic"}:
            invalid.append({"index": index, "code": "invalid_call_record"})
            continue
        if call["dispatch"] == "physical":
            event_ref = call.get("core_call_id") or call.get("physical_request_id")
            if not _nonempty_string(event_ref):
                invalid.append({"index": index, "code": "physical_event_id_missing"})
                continue
            physical_refs.setdefault(event_ref, []).append((index, call))
        elif call["dispatch"] == "cache_hit":
            cache[call["kind"]] += 1
        else:
            synthetic[call["kind"]] += 1
    duplicate_refs = []
    model_refs = []
    for event_ref, rows in physical_refs.items():
        if len(rows) != 1:
            duplicate_refs.append({"event_ref": event_ref, "call_indices": [index for index, _ in rows], "record_count": len(rows)})
            continue
        index, call = rows[0]
        physical[call["kind"]] += 1
        if (call["kind"] == "model" and call.get("outcome") == "accepted" and
                _nonempty_string(call.get("core_call_id"))):
            model_refs.append(call["core_call_id"])
    total = lambda counter: sum(counter.values())
    return {"physical_sends": {**{key: physical[key] for key in CALL_KINDS},
                                "total": total(physical), "unique_events_total": total(physical),
                                "reported_physical_records": sum(len(rows) for rows in physical_refs.values()),
                                "ambiguous_duplicate_records": sum(item["record_count"] for item in duplicate_refs)},
            "cache_hits": {**{key: cache[key] for key in CALL_KINDS}, "total": total(cache)},
            "synthetic_operations": {**{key: synthetic[key] for key in CALL_KINDS}, "total": total(synthetic)},
            "duplicate_physical_event_references": duplicate_refs,
            "fees": None, "fee_status": "unknown_not_estimated", "invalid_call_records": invalid,
            "accepted_physical_model_core_call_ids": sorted(model_refs),
            "physical_event_identity_rule": "one unique core_call_id or physical_request_id per send; repeated references are ambiguous and excluded; accepted model activation requires unique core_call_id",
            "rule_version": "unique-physical-event-reference-cache-synthetic-separated/no-cost-inference/2"}


def _recovery_metrics(run: dict[str, Any]) -> dict[str, Any]:
    records = run.get("recovery_checks", [])
    if not isinstance(records, list):
        raise EvaluationInputError("run.recovery_checks must be a list")
    counts = Counter()
    verified = matched = 0
    measured: list[float] = []
    budget_deltas: list[int] = []
    details = []
    for row in records:
        if not isinstance(row, dict) or row.get("check_type") not in RECOVERY_TYPES:
            raise EvaluationInputError("invalid recovery check record")
        evidence = _nonempty_string(row.get("core_ledger_ref"))
        state_observed = row.get("observed_state")
        state_expected = row.get("expected_state")
        state_values_valid = _nonempty_string(state_observed) and _nonempty_string(state_expected)
        budget_before, budget_after = row.get("reserved_calls_before"), row.get("reserved_calls_after")
        valid_budget = all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (budget_before, budget_after))
        is_verified = (row.get("record_origin") == "core_ledger" and evidence and
                       state_values_valid and valid_budget)
        verified += bool(is_verified)
        passed = bool(is_verified and state_observed == state_expected)
        matched += passed
        counts[row["check_type"]] += 1
        duration = row.get("measured_ms")
        has_measured_duration = (is_verified and isinstance(duration, (int, float)) and
                                 not isinstance(duration, bool) and math.isfinite(duration) and duration >= 0)
        if has_measured_duration:
            measured.append(duration)
        delta = budget_after - budget_before if is_verified else None
        if delta is not None:
            budget_deltas.append(delta)
        details.append({"check_id": row.get("check_id"), "check_type": row["check_type"],
                        "core_ledger_record_supplied": bool(is_verified), "expected_state": state_expected,
                        "observed_state": state_observed, "matched": passed,
                        "reserved_calls_before": budget_before if valid_budget else None,
                        "reserved_calls_after": budget_after if valid_budget else None,
                        "reserved_calls_delta": delta, "measured_ms": duration if has_measured_duration else None})
    return {"checks": len(records), "evidence_backed_checks": verified, "matched_expected_state_checks": matched,
            "checks_without_core_ledger_evidence": len(records) - verified,
            "by_type": {key: counts[key] for key in RECOVERY_TYPES},
            "measured_time_ms_sum": sum(measured) if measured else None,
            "measured_time_count": len(measured),
            "reserved_calls_delta_sum": sum(budget_deltas) if budget_deltas else None,
            "details": details,
            "rule_version": "caller-supplied-core-ledger-reference-required-before-recovery-evidence-counted/1"}


def _comparison(case: dict[str, Any], runs: dict[str, dict[str, Any]], reports: dict[str, Any]) -> dict[str, Any]:
    contract = {key: case.get(key) for key in ("corpus_digest", "question_digest", "model", "budget")}
    diagnostics = []
    compatible = True
    for field, expected in contract.items():
        values = {name: run.get("comparison", {}).get(field) if isinstance(run.get("comparison"), dict) else None for name, run in runs.items()}
        same_as_case = all(value == expected and value is not None for value in values.values())
        all_equal = len({json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values.values()}) == 1
        field_ok = same_as_case and all_equal
        compatible = compatible and field_ok
        diagnostics.append({"field": field, "case_value": expected, "run_values": values,
                            "same_as_frozen_case": same_as_case, "all_runs_equal": all_equal, "compatible": field_ok})
    real = True
    run_modes = {}
    model_receipts = {}
    for name, run in runs.items():
        op = reports[name]["operations"]
        mode = run.get("run_mode")
        run_modes[name] = mode
        refs = op["accepted_physical_model_core_call_ids"]
        valid = mode == "real" and bool(refs)
        model_receipts[name] = {"run_mode": mode, "accepted_physical_model_core_call_ids": refs, "real_model_receipt_present": valid}
        real = real and valid
    if not compatible:
        status = "rejected_incompatible"
    elif not real:
        status = "pending_activation"
    else:
        status = "comparable_inputs_ready_for_review"
    return {"status": status, "comparison_allowed": bool(compatible and real),
            "diagnostics": diagnostics, "run_modes": run_modes,
            "model_call_receipts": model_receipts,
            "interpretation": "Compatibility and run activation evidence are caller-supplied frozen records; this evaluator does not authenticate ledger references or infer quality deltas."}


def evaluate_bundle(case: dict[str, Any], runs: dict[str, dict[str, Any]], annotations: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(case, dict):
        raise EvaluationInputError("case must be an object")
    for field in ("case_id", "corpus_digest", "question_digest", "research_question", "evidence_bundle_digest"):
        if not _nonempty_string(case.get(field)):
            raise EvaluationInputError(f"case.{field} is required")
    if not isinstance(case.get("model"), dict) or not case["model"] or not isinstance(case.get("budget"), dict) or not case["budget"]:
        raise EvaluationInputError("case.model and case.budget objects are required")
    if set(runs) != set(ENGINES):
        raise EvaluationInputError("results must contain exactly rag, paperqa, and storm")
    evidence = _case_evidence(case)
    expected_evidence_digest = "sha256:" + canonical_digest(case["evidence"])
    expected_question_digest = "sha256:" + hashlib.sha256(case["research_question"].encode("utf-8")).hexdigest()
    if case["evidence_bundle_digest"] != expected_evidence_digest:
        raise EvaluationInputError("case.evidence_bundle_digest does not match canonical frozen evidence")
    if case["question_digest"] != expected_question_digest:
        raise EvaluationInputError("case.question_digest does not match research_question UTF-8 bytes")
    composition = case.get("sample_composition", {})
    if not isinstance(composition, dict) or any(not _nonempty_string(k) or isinstance(v, bool) or not isinstance(v, int) or v < 0 for k, v in composition.items()):
        raise EvaluationInputError("case.sample_composition must map sample kinds to non-negative integer counts")
    if composition and sum(composition.values()) != len(evidence):
        raise EvaluationInputError("case.sample_composition counts must sum to frozen evidence count")
    reports = {}
    for name in ENGINES:
        run = runs[name]
        if (not isinstance(run, dict) or run.get("engine") != name or run.get("frozen_result") is not True or
                run.get("run_mode") not in {"real", "offline_synthetic", "offline_library_smoke", "pending_activation"}):
            raise EvaluationInputError(f"{name}: expected frozen_result=true, matching engine and recognized run_mode")
        reports[name] = {
            "run_id": run.get("run_id"), "run_mode": run.get("run_mode"),
            "source_evidence_basis": "synthetic_fixture" if run.get("run_mode") == "offline_synthetic" else "provided_frozen_run_record",
            "claim_count": len(run.get("claims", [])) if isinstance(run.get("claims", []), list) else None,
            "citation_metrics": _citation_metrics(case, run),
            "semantic_support": _semantic_metrics(run, annotations),
            "coverage": _coverage_metrics(case, run),
            "operations": _operations_metrics(run),
            "recovery": _recovery_metrics(run),
        }
    comparison = _comparison(case, runs, reports)
    annotation_present = bool(annotations is not None and
                              any(isinstance(row, dict) and row.get("label") in SEMANTIC_LABELS
                                  for row in annotations.get("claims", [])))
    return {"evaluation_rule_version": RULE_VERSION,
            "case_id": case.get("case_id"), "case_mode": case.get("case_mode", "unspecified"),
            "scientific_support_interpretation": "human annotations only; not annotated claims are not supported",
            "fixed_evidence_count": len(evidence),
            "sample_composition": composition,
            "sample_scope": "fixed case only; no global corpus recall claim",
            "quote_normalization_rule": QUOTE_RULE,
            "case_digest_rule": CASE_DIGEST_RULE,
            "evidence_bundle_digest": expected_evidence_digest,
            "annotation_present": annotation_present,
            "runs": reports, "comparison": comparison}
