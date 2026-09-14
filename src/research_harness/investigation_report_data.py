"""Build frozen, evidence-checked ReportData without generating research prose."""
from __future__ import annotations

import copy
from typing import Any

from .errors import ValidationError


def _issue(code: str, message: str, **context: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **context}


def _unique(items: list[dict[str, Any]], field: str) -> None:
    values = [item.get(field) for item in items]
    if not all(isinstance(value, str) and value for value in values) or len(values) != len(set(values)):
        raise ValidationError(f"{field} must be present and unique")


def _refs(claim: dict[str, Any]) -> list[dict[str, Any]]:
    refs = claim.get("evidence_refs", [])
    if not isinstance(refs, list): return []
    result = []
    for item in refs:
        result.append({"evidence_id": item} if isinstance(item, str) else item)
    return result


def validate_claims(evidence: list[dict[str, Any]], findings: list[dict[str, Any]], claims: list[dict[str, Any]], verification: dict[str, Any]) -> dict[str, Any]:
    """Validate identity/quote/index invariants and return safe diagnostic data."""
    if not all(isinstance(value, list) for value in (evidence, findings, claims)) or not isinstance(verification, dict):
        raise ValidationError("evidence, findings, claims and verification have invalid shape")
    if not all(isinstance(item, dict) for item in [*evidence, *findings, *claims]): raise ValidationError("report facts must contain objects")
    _unique(evidence, "evidence_id"); _unique(findings, "finding_id"); _unique(claims, "claim_id")
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    for finding in findings:
        if any(field not in finding for field in ("finding", "evidence_ids", "value", "unit", "conditions")) or not isinstance(finding["evidence_ids"], list) or any(ref not in evidence_by_id for ref in finding["evidence_ids"]):
            raise ValidationError("finding has invalid fields or evidence_ids")
    for claim in claims:
        if any(field not in claim for field in ("claim", "finding_refs", "evidence_refs", "quote", "document_id", "version_id")):
            raise ValidationError("claim has invalid fields")
    supported = verification.get("supported_claim_refs", [])
    if not isinstance(supported, list) or not all(isinstance(index, int) for index in supported):
        raise ValidationError("supported_claim_refs must be integer indexes")
    if any(index < 0 or index >= len(claims) for index in supported): raise ValidationError("supported_claim_refs is out of bounds")
    verified = verification.get("status") == "verified"
    issues: list[dict[str, Any]] = []; valid: list[str] = []; draft: list[str] = []
    for index, claim in enumerate(claims):
        claim_id = claim["claim_id"]; reasons = []
        finding_refs = claim.get("finding_refs", [])
        if not isinstance(finding_refs, list) or not all(isinstance(ref, int) and 0 <= ref < len(findings) for ref in finding_refs):
            reasons.append("finding_refs is invalid")
        if not verified or index not in supported:
            reasons.append("claim is not supported by verification")
        refs = _refs(claim)
        if not refs: reasons.append("claim has no evidence reference")
        for ref in refs:
            if not isinstance(ref, dict) or not isinstance(ref.get("evidence_id"), str):
                reasons.append("evidence reference is invalid"); continue
            item = evidence_by_id.get(ref["evidence_id"])
            if not item:
                reasons.append(f"unknown evidence {ref['evidence_id']}"); continue
            quote = ref.get("quote", claim.get("quote")); document_id = ref.get("document_id", claim.get("document_id")); version_id = ref.get("version_id", claim.get("version_id"))
            if not item.get("document_id") or not item.get("version_id") or not item.get("locator"):
                reasons.append(f"evidence {ref['evidence_id']} lacks identity or locator")
            if document_id != item.get("document_id") or version_id != item.get("version_id"):
                reasons.append(f"evidence {ref['evidence_id']} document/version mismatch")
            if not isinstance(quote, str) or not quote or quote not in str(item.get("text", "")):
                reasons.append(f"evidence {ref['evidence_id']} quote is not a continuous original substring")
        if not reasons and len(finding_refs) > 1:
            conditions = {_stable_condition(findings[ref].get("conditions")) for ref in finding_refs}
            if len(conditions) > 1:
                reasons.append("not-comparable: referenced findings have different conditions")
                issues.append(_issue("RH_NOT_COMPARABLE", "cross-finding conditions differ; deterministic comparative conclusion is blocked", claim_id=claim_id, finding_refs=finding_refs))
        if reasons:
            draft.append(claim_id); issues.append(_issue("RH_CLAIM_DRAFT", "; ".join(dict.fromkeys(reasons)), claim_id=claim_id))
        else: valid.append(claim_id)
    return {"valid_claim_ids": valid, "draft_claim_ids": draft, "issues": issues}


def _stable_condition(value: Any) -> str:
    if isinstance(value, (dict, list)): return repr(sorted(value.items()) if isinstance(value, dict) else value)
    return repr(value)


def _report_targets(spec: dict[str, Any], sections: list[dict[str, Any]]) -> list[Any]:
    targets = spec.get("report_targets")
    if targets is not None:
        if not isinstance(targets, list): raise ValidationError("spec.report_targets must be a list")
        return copy.deepcopy(targets)
    return [{"deliverable_type": section.get("deliverable_type"), "languages": [section.get("language")]} for section in sections]


def build_report_data(run_id: str, spec: dict[str, Any], evidence: list[dict[str, Any]], findings: list[dict[str, Any]], claims: list[dict[str, Any]], sections: list[dict[str, Any]], verification: dict[str, Any], bibliography: list[dict[str, Any]], coverage: dict[str, Any], issues: list[dict[str, Any]], report_version: str = "v1") -> dict[str, Any]:
    """Freeze supplied model facts into ReportData consumable by ``export_reports``.

    The raw values remain available under ``raw_model_output``.  Invalid facts
    become draft diagnostics and are never copied into a reader-facing section.
    """
    if not isinstance(run_id, str) or not run_id or not isinstance(spec, dict): raise ValidationError("run_id and spec are required")
    if not all(isinstance(value, list) for value in (evidence, findings, claims, sections, bibliography, issues)) or not isinstance(coverage, dict):
        raise ValidationError("report inputs have invalid shape")
    validation = validate_claims(evidence, findings, claims, verification)
    valid = set(validation["valid_claim_ids"]); result_issues = [*copy.deepcopy(issues), *validation["issues"]]
    checked_claims = []
    for claim in claims:
        item = copy.deepcopy(claim)
        item["verification"] = "verified" if item["claim_id"] in valid else "draft"
        checked_claims.append(item)
    checked_sections = []
    for section in sections:
        if not isinstance(section, dict): raise ValidationError("sections must contain objects")
        if any(field not in section for field in ("deliverable_type", "language", "section_id", "title", "body", "claim_ids")):
            raise ValidationError("section has invalid fields")
        claim_ids = section.get("claim_ids", [])
        if not isinstance(claim_ids, list): raise ValidationError("section claim_ids must be a list")
        missing = [claim_id for claim_id in claim_ids if claim_id not in valid]
        if missing:
            result_issues.append(_issue("RH_SECTION_DRAFT", "section references unverified or invalid claims and is withheld", section_id=section.get("section_id"), claim_ids=missing))
            continue
        checked_sections.append(copy.deepcopy(section))
    targets = _report_targets(spec, sections)
    for target in targets:
        kind = target if isinstance(target, str) else target.get("deliverable_type") if isinstance(target, dict) else None
        languages = [] if isinstance(target, str) else target.get("languages", [])
        if languages and isinstance(languages, list):
            for language in languages:
                if not any(section.get("deliverable_type") == kind and section.get("language") == language for section in checked_sections):
                    result_issues.append(_issue("RH_REPORT_LANGUAGE_MISSING", "host did not provide a verified body in requested language", deliverable_type=kind, language=language))
    return {"synthetic": bool(spec.get("synthetic", spec.get("data_mode") == "synthetic")), "run_id": run_id, "report_version": report_version,
            "research_question": spec.get("research_question"), "spec": copy.deepcopy(spec), "report_targets": targets,
            "findings": copy.deepcopy(findings), "evidence": copy.deepcopy(evidence), "claims": checked_claims,
            "sections": checked_sections, "bibliography": copy.deepcopy(bibliography), "coverage": copy.deepcopy(coverage),
            "issues": result_issues, "validation": {"outcome": "completed" if not validation["draft_claim_ids"] else "partial", **validation},
            "raw_model_output": {"findings": copy.deepcopy(findings), "claims": copy.deepcopy(claims), "sections": copy.deepcopy(sections), "verification": copy.deepcopy(verification)}}
