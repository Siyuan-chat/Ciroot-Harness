"""Deterministic, offline rendering for frozen investigation ``ReportData``.

The renderer deliberately does not infer or translate research content.  It
only projects supplied, verified sections into reader-facing artifacts.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
from pathlib import Path
from typing import Any

from .errors import ExportError, ValidationError


_TYPES = {"technical_report", "literature_review", "patent_monitor_digest"}
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DANGEROUS_CSV = ("=", "+", "-", "@")


class ReportExportError(ExportError):
    """A stable, safe error for attempts to replace frozen report facts."""

    code = "RH_REPORT_EXPORT"

    def __init__(self, message: str = "report export failed"):
        self.message = message


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _component(value: Any, name: str) -> str:
    text = str(value)
    if not _SAFE_COMPONENT.fullmatch(text) or text in {".", ".."}:
        raise ValidationError(f"{name} must be a safe path component")
    return text


def _safe_csv(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_DANGEROUS_CSV) else text


def _bib(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ")


def _write(path: Path, data: str | bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _artifact(path: Path, root: Path, kind: str, version: str, language: str | None, fmt: str, digest: str) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    return {"artifact_id": _digest([kind, version, language, fmt, relative])[:20], "type": kind,
            "version": version, "language": language, "format": fmt, "path": relative, "sha256": digest}


def _claim_ok(claim: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> tuple[bool, str | None]:
    verification = claim.get("verification")
    verified = verification is True or verification == "verified" or (
        isinstance(verification, dict) and verification.get("status") == "verified"
    )
    if not verified:
        return False, "claim is not verified"
    refs = claim.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        return False, "claim has no evidence_refs"
    for ref in refs:
        if isinstance(ref, str):
            evidence_id, quote, document_id, version_id = ref, claim.get("quote"), claim.get("document_id"), claim.get("version_id")
        elif isinstance(ref, dict):
            evidence_id = ref.get("evidence_id")
            quote = ref.get("quote", claim.get("quote"))
            document_id = ref.get("document_id", claim.get("document_id"))
            version_id = ref.get("version_id", claim.get("version_id"))
        else:
            return False, "evidence reference has invalid shape"
        item = evidence.get(str(evidence_id))
        if not item:
            return False, f"unknown evidence {evidence_id!r}"
        if not item.get("document_id") or not item.get("version_id") or not item.get("locator"):
            return False, f"evidence {evidence_id!r} lacks document identity or locator"
        if document_id is not None and document_id != item["document_id"]:
            return False, f"evidence {evidence_id!r} belongs to another document"
        if version_id is not None and version_id != item["version_id"]:
            return False, f"evidence {evidence_id!r} belongs to another version"
        if not isinstance(quote, str) or not quote or quote not in str(item.get("text", "")):
            return False, f"claim quotation does not match evidence {evidence_id!r}"
    return True, None


def _render_markdown(section: dict[str, Any]) -> str:
    citations = ", ".join(f"[{item}]" for item in section.get("claim_ids", []))
    suffix = f"\n\nEvidence claims: {citations}" if citations else ""
    return f"# {section['title']}\n\n{section['body']}{suffix}\n"


def _render_html(section: dict[str, Any]) -> str:
    citations = " ".join(f"<code>{html.escape(str(item))}</code>" for item in section.get("claim_ids", []))
    suffix = f"<p>Evidence claims: {citations}</p>" if citations else ""
    body = "<br>".join(html.escape(line) for line in str(section["body"]).splitlines())
    return f"<!doctype html><html lang=\"{html.escape(str(section['language']), quote=True)}\"><body><h1>{html.escape(str(section['title']))}</h1><p>{body}</p>{suffix}</body></html>"


def _csv_text(rows: list[list[Any]]) -> str:
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerows([[_safe_csv(value) for value in row] for row in rows])
    return handle.getvalue()


def _bibtex(items: list[dict[str, Any]]) -> str:
    entries: list[str] = []
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or not item.get("title"):
            continue
        key = str(item.get("citation_key") or item.get("doi") or item.get("id") or f"reference{index}")
        fields = [(key, value) for key, value in item.items() if key not in {"citation_key", "id", "type"} and value not in (None, "")]
        rendered = ",\n  ".join(f"{name} = {{{_bib(value)}}}" for name, value in fields)
        entries.append(f"@{item.get('type', 'article')}{{{_bib(key)},\n  {rendered}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def export_reports(workspace: str | Path, run_id: str, report_data: dict[str, Any], languages: list[str] | None = None) -> dict[str, Any]:
    """Export frozen report data without network, model, or database access.

    Invalid claims are retained in canonical JSON as invalid drafts but never
    projected into Markdown/HTML.  Repeating identical data reuses a manifest;
    changing facts under the same version is rejected.
    """
    if not isinstance(report_data, dict):
        raise ValidationError("report_data must be an object")
    required = ("synthetic", "report_version", "findings", "evidence", "sections", "bibliography", "coverage", "issues")
    missing = [name for name in required if name not in report_data]
    if missing or not (report_data.get("research_question") or report_data.get("spec")):
        raise ValidationError("report_data is missing required frozen fields")
    run = _component(run_id, "run_id")
    version = _component(report_data["report_version"], "report_version")
    root = Path(workspace).resolve()
    target = (root / "reports" / run / version).resolve()
    if root not in target.parents:
        raise ValidationError("report export path escapes workspace")
    fingerprint = _digest(report_data)
    manifest_path = target / "export-manifest.json"
    prior_languages: list[str] = []
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prior.get("report_data_sha256") != fingerprint:
            raise ReportExportError("refusing to overwrite a frozen report version with different facts")
        prior_languages = list(prior.get("requested_languages", []))
        if languages is None or set(languages).issubset(prior_languages):
            return {key: prior[key] for key in ("run_id", "report_version", "artifacts", "status", "issues")}

    evidence_items = report_data.get("evidence")
    claims_items = report_data.get("claims", [])
    sections = report_data.get("sections")
    if not all(isinstance(value, list) for value in (evidence_items, claims_items, sections)):
        raise ValidationError("evidence, claims and sections must be lists")
    evidence = {str(item.get("evidence_id")): item for item in evidence_items if isinstance(item, dict) and item.get("evidence_id")}
    claims = {str(item.get("claim_id")): item for item in claims_items if isinstance(item, dict) and item.get("claim_id")}
    supplied_languages = languages if languages is not None else [str(s.get("language")) for s in sections if isinstance(s, dict) and s.get("language")]
    requested = list(dict.fromkeys([*prior_languages, *supplied_languages]))
    if not requested:
        raise ValidationError("at least one report language is required")
    issues = list(report_data.get("issues") or [])
    artifacts: list[dict[str, Any]] = []
    canonical = dict(report_data)
    canonical["report_status"] = "draft"  # promoted only after render validation below
    canonical["export_validation"] = {"report_data_sha256": fingerprint, "invalid_sections": []}
    artifacts.append(_artifact(target / "report-data.canonical.json", root, "canonical", version, None, "canonical_json", _write(target / "report-data.canonical.json", json.dumps(canonical, ensure_ascii=False, indent=2) + "\n")))

    for kind in _TYPES:
        for language in requested:
            matching = [s for s in sections if isinstance(s, dict) and s.get("deliverable_type") == kind and s.get("language") == language]
            if not matching:
                issues.append({"code": "RH_REPORT_LANGUAGE_MISSING", "type": kind, "language": language, "message": "no supplied body for requested language"})
                continue
            for section in matching:
                if not isinstance(section.get("section_id"), str) or not isinstance(section.get("title"), str) or not isinstance(section.get("body"), str):
                    issues.append({"code": "RH_REPORT_SECTION_INVALID", "type": kind, "language": language, "section_id": section.get("section_id"), "message": "section lacks supplied title or body"})
                    canonical["export_validation"]["invalid_sections"].append(section.get("section_id"))
                    continue
                bad = []
                for claim_id in section.get("claim_ids", []):
                    claim = claims.get(str(claim_id))
                    okay, reason = _claim_ok(claim, evidence) if claim else (False, "unknown claim")
                    if not okay:
                        bad.append({"claim_id": claim_id, "reason": reason})
                if bad:
                    issues.append({"code": "RH_REPORT_CITATION_INVALID", "type": kind, "language": language, "section_id": section["section_id"], "claims": bad})
                    canonical["export_validation"]["invalid_sections"].append(section["section_id"])
                    continue
                base = f"{kind}.{language}.{_component(section['section_id'], 'section_id')}"
                markdown_path = target / f"{base}.md"
                html_path = target / f"{base}.html"
                artifacts.append(_artifact(markdown_path, root, kind, version, language, "markdown", _write(markdown_path, _render_markdown(section))))
                artifacts.append(_artifact(html_path, root, kind, version, language, "html", _write(html_path, _render_html(section))))

    comparison_rows = [["finding_id", "value", "unit", "conditions", "evidence_refs"]]
    for item in report_data.get("findings", []):
        if isinstance(item, dict): comparison_rows.append([item.get("finding_id", ""), item.get("value", ""), item.get("unit", ""), item.get("conditions", ""), json.dumps(item.get("evidence_refs", []), ensure_ascii=False)])
    comparison_path = target / "comparison.csv"
    artifacts.append(_artifact(comparison_path, root, "comparison", version, None, "comparison_csv", _write(comparison_path, _csv_text(comparison_rows))))
    review_rows = [["issue_id", "status", "reason", "claim_ids"]]
    for item in issues:
        if isinstance(item, dict): review_rows.append([item.get("issue_id", ""), item.get("status", "open"), item.get("message", item.get("reason", "")), json.dumps(item.get("claim_ids", item.get("claims", [])), ensure_ascii=False)])
    review_path = target / "human-review.csv"
    artifacts.append(_artifact(review_path, root, "human_review", version, None, "review_csv", _write(review_path, _csv_text(review_rows))))
    bib_path = target / "bibliography.bib"
    artifacts.append(_artifact(bib_path, root, "bibliography", version, None, "bibtex", _write(bib_path, _bibtex(report_data.get("bibliography", [])))))

    # Rewrite canonical after the full validation result is known; its original
    # report_data payload remains preserved, while invalid sections stay drafts.
    canonical["report_status"] = "draft" if canonical["export_validation"]["invalid_sections"] else "verified"
    canonical_digest = _write(target / "report-data.canonical.json", json.dumps(canonical, ensure_ascii=False, indent=2) + "\n")
    artifacts[0]["sha256"] = canonical_digest
    status = "partial" if issues else "completed"
    manifest = {"run_id": run, "report_version": version, "report_data_sha256": fingerprint, "requested_languages": requested, "artifacts": artifacts, "status": status, "issues": issues}
    _write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {key: manifest[key] for key in ("run_id", "report_version", "artifacts", "status", "issues")}
