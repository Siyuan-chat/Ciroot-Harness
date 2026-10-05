"""Build frozen, evidence-checked ReportData without generating research prose."""
from __future__ import annotations

import copy
import re
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
        if isinstance(item, str):
            normalized = {"evidence_id": item}
            if isinstance(claim.get("parse_revision_id"), str):
                normalized["parse_revision_id"] = claim["parse_revision_id"]
            result.append(normalized)
        else:
            result.append(item)
    return result


def validate_claims(evidence: list[dict[str, Any]], findings: list[dict[str, Any]], claims: list[dict[str, Any]], verification: dict[str, Any]) -> dict[str, Any]:
    """Validate identity/quote/index invariants and return safe diagnostic data."""
    if not all(isinstance(value, list) for value in (evidence, findings, claims)) or not isinstance(verification, dict):
        raise ValidationError("evidence, findings, claims and verification have invalid shape")
    if not all(isinstance(item, dict) for item in [*evidence, *findings, *claims]): raise ValidationError("report facts must contain objects")
    _unique(evidence, "evidence_id"); _unique(findings, "finding_id"); _unique(claims, "claim_id")
    evidence_by_id = {item["evidence_id"]: item for item in evidence}
    for finding in findings:
        if any(field not in finding for field in ("finding", "evidence_ids", "value", "unit", "conditions")) or not isinstance(finding["evidence_ids"], list) or not finding["evidence_ids"] or any(ref not in evidence_by_id for ref in finding["evidence_ids"]):
            raise ValidationError("finding has invalid fields or evidence_ids")
    for claim in claims:
        if any(field not in claim for field in ("claim", "finding_refs", "evidence_refs", "quote", "document_id", "version_id")):
            raise ValidationError("claim has invalid fields")
    supported = verification.get("supported_claim_refs", [])
    if not isinstance(supported, list) or not all(isinstance(index, int) for index in supported):
        raise ValidationError("supported_claim_refs must be integer indexes")
    if any(index < 0 or index >= len(claims) for index in supported): raise ValidationError("supported_claim_refs is out of bounds")
    verification_status = verification.get("status")
    verified = verification_status in {"supported", "partial"}
    issues: list[dict[str, Any]] = []; valid: list[str] = []; draft: list[str] = []
    for index, claim in enumerate(claims):
        claim_id = claim["claim_id"]; reasons = []
        finding_refs = claim.get("finding_refs", [])
        if not isinstance(finding_refs, list) or not finding_refs or not all(isinstance(ref, int) and 0 <= ref < len(findings) for ref in finding_refs):
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
                reasons.append("evidence reference is unknown"); continue
            quote = ref.get("quote", claim.get("quote")); document_id = ref.get("document_id", claim.get("document_id")); version_id = ref.get("version_id", claim.get("version_id"))
            if not item.get("document_id") or not item.get("version_id") or not item.get("locator"):
                reasons.append("evidence lacks identity or locator")
            if document_id != item.get("document_id") or version_id != item.get("version_id"):
                reasons.append("evidence document/version mismatch")
            if item.get("parse_revision_id") and ref.get("parse_revision_id", claim.get("parse_revision_id")) != item.get("parse_revision_id"):
                reasons.append("evidence parse revision mismatch or missing")
            if not isinstance(quote, str) or not quote or quote not in str(item.get("text", "")):
                reasons.append("evidence quote is not a continuous original substring")
        if isinstance(finding_refs, list) and finding_refs and all(isinstance(ref, int) and 0 <= ref < len(findings) for ref in finding_refs):
            allowed = {evidence_id for finding_ref in finding_refs for evidence_id in findings[finding_ref]["evidence_ids"]}
            if any(not isinstance(ref, dict) or ref.get("evidence_id") not in allowed for ref in refs):
                reasons.append("claim evidence is not bound to referenced findings")
            conditions = [findings[ref].get("conditions") for ref in finding_refs]
            if len(finding_refs) > 1 and (any(condition is None for condition in conditions) or len({_stable_condition(condition) for condition in conditions}) > 1):
                reasons.append("not-comparable: referenced findings have different conditions")
                issues.append(_issue("RH_NOT_COMPARABLE", "cross-finding conditions are missing or differ; deterministic comparative conclusion is blocked", claim_id=claim_id, finding_refs=finding_refs))
        if reasons:
            draft.append(claim_id); issues.append(_issue("RH_CLAIM_DRAFT", "; ".join(dict.fromkeys(reasons)), claim_id=claim_id))
        else: valid.append(claim_id)
    return {"valid_claim_ids": valid, "draft_claim_ids": draft, "issues": issues}


def _stable_condition(value: Any) -> str:
    if isinstance(value, (dict, list)): return repr(sorted(value.items()) if isinstance(value, dict) else value)
    return repr(value)


def _claim_checks(evidence: list[dict[str, Any]], findings: list[dict[str, Any]], claim: dict[str, Any], index: int, verification: dict[str, Any]) -> dict[str, Any]:
    """Keep provenance, quote matching, and verifier acceptance distinct."""
    evidence_by_id = {item.get("evidence_id"): item for item in evidence}
    refs = _refs(claim)
    identity_ok = locator_ok = quote_match = parse_revision_ok = bool(refs)
    for ref in refs:
        if not isinstance(ref, dict) or not isinstance(ref.get("evidence_id"), str):
            identity_ok = locator_ok = quote_match = parse_revision_ok = False
            continue
        item = evidence_by_id.get(ref["evidence_id"])
        if not item:
            identity_ok = locator_ok = quote_match = parse_revision_ok = False
            continue
        if (ref.get("document_id", claim.get("document_id")) != item.get("document_id") or
                ref.get("version_id", claim.get("version_id")) != item.get("version_id")):
            identity_ok = False
        if not item.get("document_id") or not item.get("version_id"):
            identity_ok = False
        if not item.get("locator"):
            locator_ok = False
        if item.get("parse_revision_id") and ref.get("parse_revision_id", claim.get("parse_revision_id")) != item.get("parse_revision_id"):
            parse_revision_ok = False
        quote = ref.get("quote", claim.get("quote"))
        if not isinstance(quote, str) or not quote or quote not in str(item.get("text", "")):
            quote_match = False
    finding_refs = claim.get("finding_refs", [])
    finding_binding_ok = (isinstance(finding_refs, list) and bool(finding_refs) and
                          all(isinstance(ref, int) and 0 <= ref < len(findings) for ref in finding_refs))
    if finding_binding_ok:
        allowed = {evidence_id for finding_ref in finding_refs for evidence_id in findings[finding_ref].get("evidence_ids", [])}
        finding_binding_ok = bool(refs) and all(isinstance(ref, dict) and ref.get("evidence_id") in allowed for ref in refs)
    verifier_status = verification.get("status") in {"supported", "partial"}
    accepted = verifier_status and index in verification.get("supported_claim_refs", [])
    return {
        "identity": "pass" if identity_ok else "fail",
        "parse_revision": "pass" if parse_revision_ok else "fail",
        "locator": "pass" if locator_ok else "fail",
        "quote_match": "matched" if quote_match else "unmatched",
        "quote_match_note": "substring match records provenance only; it is not semantic support",
        "finding_binding": "pass" if finding_binding_ok else "fail",
        "independent_verifier": "accepted" if accepted else "not_accepted",
    }


def _language_hint(value: str) -> str:
    kana = sum("\u3040" <= char <= "\u30ff" for char in value)
    han = sum("\u3400" <= char <= "\u9fff" for char in value)
    hangul = sum("\uac00" <= char <= "\ud7af" or "\u1100" <= char <= "\u11ff" for char in value)
    latin = sum(char.isascii() and char.isalpha() for char in value)
    if kana and not hangul and not latin:
        return "ja"
    if hangul and not kana and not latin and not han:
        return "ko"
    if (kana or han or hangul) and latin:
        return "mixed"
    if hangul or kana:
        return "mixed"
    # Han-only text can be Chinese or Japanese, so leave it unresolved.
    if han:
        return "und"
    if latin:
        return "en"
    return "und"


def _accepted_section_title(language: str) -> str:
    return {"zh": "已核验主张", "ja": "検証済みの主張", "ko": "검증된 주장"}.get(language, "Verified claims")


def _gap_projection(coverage: dict[str, Any], issues: list[dict[str, Any]], language: str, section_id: str) -> dict[str, Any] | None:
    """Create a reader gap only from core-owned status fields and issue codes."""
    coverage_refs = ["coverage.complete"] if coverage.get("complete") is False else []
    issue_refs = sorted({item["code"] for item in issues
                         if isinstance(item, dict) and isinstance(item.get("code"), str)
                         and re.fullmatch(r"RH_[A-Z0-9_]+", item["code"])})
    if not coverage_refs and not issue_refs:
        return None
    if language == "zh":
        parts = []
        if coverage_refs: parts.append("冻结运行记录标记覆盖不完整。")
        if issue_refs: parts.append("记录的问题代码：" + ", ".join(issue_refs) + "。")
    elif language == "ja":
        parts = []
        if coverage_refs: parts.append("凍結実行記録ではカバレッジが不完全です。")
        if issue_refs: parts.append("記録された問題コード：" + ", ".join(issue_refs) + "。")
    elif language == "ko":
        parts = []
        if coverage_refs: parts.append("고정 실행 기록에서 커버리지가 불완전하다고 표시되었습니다.")
        if issue_refs: parts.append("기록된 문제 코드: " + ", ".join(issue_refs) + ".")
    else:
        parts = []
        if coverage_refs: parts.append("The frozen run record marks coverage as incomplete.")
        if issue_refs: parts.append("Recorded issue codes: " + ", ".join(issue_refs) + ".")
    return {"block_id": f"{section_id}:gap", "kind": "gap", "issue_refs": issue_refs,
            "coverage_refs": coverage_refs, "text": " ".join(parts)}


def _project_sections(sections: list[dict[str, Any]], checked_claims: list[dict[str, Any]], valid_claim_ids: set[str],
                      coverage: dict[str, Any], source_issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project reader sections solely from accepted claims plus core gap metadata."""
    claims_by_id = {str(claim["claim_id"]): claim for claim in checked_claims}
    checked_sections: list[dict[str, Any]] = []
    result_issues: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValidationError("sections must contain objects")
        if any(field not in section for field in ("deliverable_type", "language", "section_id", "title", "body", "claim_ids")):
            raise ValidationError("section has invalid fields")
        requested_kind = section.get("block_kind", section.get("section_kind", "fact"))
        if section.get("block_kind") and section.get("section_kind") and section["block_kind"] != section["section_kind"]:
            requested_kind = "invalid"
        if requested_kind not in {"fact", "explanation", "method"}:
            result_issues.append(_issue("RH_SECTION_KIND_DRAFT", "unsupported section kind is withheld; only fact, explanation, and method projections are accepted", section_id=section.get("section_id"), section_kind=requested_kind))
            continue
        claim_ids = section.get("claim_ids", [])
        if not isinstance(claim_ids, list) or not claim_ids or not all(isinstance(value, str) for value in claim_ids) or len(claim_ids) != len(set(claim_ids)):
            result_issues.append(_issue("RH_SECTION_DRAFT", "section must reference distinct independently accepted claims", section_id=section.get("section_id")))
            continue
        missing = [claim_id for claim_id in claim_ids if not isinstance(claim_id, str) or claim_id not in valid_claim_ids]
        if missing:
            result_issues.append(_issue("RH_SECTION_DRAFT", "section references unverified or invalid claims and is withheld", section_id=section.get("section_id"), claim_ids=missing))
            continue
        blocks = [{"block_id": f"{section['section_id']}:{requested_kind}:{claim_id}", "kind": requested_kind,
                   "claim_id": claim_id, "text": claims_by_id[claim_id]["claim"]} for claim_id in claim_ids]
        item = copy.deepcopy(section)
        item["section_kind"] = requested_kind
        item["blocks"] = blocks
        item["title"] = _accepted_section_title(section["language"])
        body = "\n\n".join(block["text"] for block in blocks)
        if section["title"] != item["title"]:
            result_issues.append(_issue("RH_SECTION_TITLE_DRAFT", "free section title retained for diagnosis; reader title uses a fixed localized label", section_id=section.get("section_id")))
        if section["body"] != body:
            result_issues.append(_issue("RH_SECTION_DRAFT", "free report prose retained for diagnosis; reader body was assembled from independently accepted claims", section_id=section.get("section_id")))
        checked_sections.append(item)

    # Project run-recorded gaps once per deliverable/language, attached only to
    # an already accepted section. No model-provided gap text is copied.
    seen_targets: set[tuple[str, str]] = set()
    for item in checked_sections:
        target = (str(item["deliverable_type"]), str(item["language"]))
        if target in seen_targets:
            continue
        seen_targets.add(target)
        gap = _gap_projection(coverage, source_issues, target[1], str(item["section_id"]))
        if gap is not None:
            item["blocks"].append(gap)
    for item in checked_sections:
        item["body"] = "\n\n".join(block["text"] for block in item["blocks"])
        item["source_language_hint"] = _language_hint(item["body"])
    return checked_sections, result_issues


def _report_targets(spec: dict[str, Any], sections: list[dict[str, Any]]) -> list[Any]:
    targets = spec.get("report_targets")
    if targets is None:
        targets = [section.get("deliverable_type") for section in sections]
    if not isinstance(targets, list): raise ValidationError("spec.report_targets must be a list")
    normalized = []
    for target in targets:
        kind = target if isinstance(target, str) else target.get("deliverable_type") if isinstance(target, dict) else None
        languages = [] if isinstance(target, str) else target.get("languages", [])
        if not isinstance(languages, list): raise ValidationError("report target languages must be a list")
        if not languages: languages = [section.get("language") for section in sections if section.get("deliverable_type") == kind]
        normalized.append({"deliverable_type": kind, "languages": list(dict.fromkeys(language for language in languages if language))})
    return normalized


def _synthetic(spec: dict[str, Any]) -> bool:
    if "synthetic" in spec: return bool(spec["synthetic"])
    runtime = spec.get("runtime", {})
    if spec.get("data_mode") == "synthetic" or isinstance(runtime, dict) and runtime.get("data_mode") == "synthetic": return True
    return False if spec.get("data_mode") == "live" or isinstance(runtime, dict) and runtime.get("data_mode") == "live" else True


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
    if coverage.get("complete") is False:
        result_issues.append(_issue("RH_REPORT_COVERAGE_INCOMPLETE", "coverage is marked incomplete in the frozen run record"))
    checked_claims = []
    for index, claim in enumerate(claims):
        item = copy.deepcopy(claim)
        item["verification"] = "verified" if item["claim_id"] in valid else "draft"
        checks = _claim_checks(evidence, findings, claim, index, verification)
        item["report_checks"] = checks
        checked_claims.append(item)
    checked_sections, section_issues = _project_sections(sections, checked_claims, valid, coverage, issues)
    result_issues.extend(section_issues)
    for section in checked_sections:
        if section["source_language_hint"] != section["language"]:
            result_issues.append(_issue("RH_REPORT_LANGUAGE_UNVERIFIED", "report blocks are rendered with a heuristic source-language hint; no translation was accepted", section_id=section.get("section_id"), requested_language=section["language"], source_language_hint=section["source_language_hint"]))
    targets = _report_targets(spec, sections)
    for target in targets:
        kind = target.get("deliverable_type")
        languages = target.get("languages", [])
        target_sections = [section for section in checked_sections if section.get("deliverable_type") == kind]
        if not target_sections:
            result_issues.append(_issue("RH_REPORT_BODY_MISSING", "requested report target has no verified body", deliverable_type=kind))
        if languages:
            for language in languages:
                if not any(section.get("language") == language for section in target_sections):
                    result_issues.append(_issue("RH_REPORT_LANGUAGE_MISSING", "host did not provide a verified body in requested language", deliverable_type=kind, language=language))
    if targets and (not evidence or not valid):
        result_issues.append(_issue("RH_REPORT_NO_SUPPORTED_EVIDENCE", "a research report requires normalized evidence and at least one supported claim"))
    checked_findings = []
    for finding in findings:
        item = copy.deepcopy(finding); item["evidence_refs"] = copy.deepcopy(finding["evidence_ids"]); checked_findings.append(item)
    outcome = "partial" if result_issues or verification.get("status") == "partial" else "completed"
    return {"synthetic": _synthetic(spec), "run_id": run_id, "report_version": report_version,
            "report_contract_version": "report-block-v2",
            "research_question": spec.get("research_question"), "spec": copy.deepcopy(spec), "report_targets": targets,
            "findings": checked_findings, "evidence": copy.deepcopy(evidence), "claims": checked_claims,
            "sections": checked_sections, "bibliography": copy.deepcopy(bibliography), "coverage": copy.deepcopy(coverage),
            "issues": result_issues, "validation": {"outcome": outcome, **validation},
            "report_contract_sources": {"coverage": copy.deepcopy(coverage), "issues": copy.deepcopy(issues)},
            "raw_model_output": {"findings": copy.deepcopy(findings), "claims": copy.deepcopy(claims), "sections": copy.deepcopy(sections), "verification": copy.deepcopy(verification)}}
