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
_DANGEROUS_CSV = ("=", "+", "-", "@", "\t", "\r")


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
    return str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", " ").replace("\r", " ")


def _citation_key(item: dict[str, Any], index: int) -> str:
    explicit = item.get("citation_key")
    if explicit is not None:
        return str(explicit)
    identity = item.get("doi") or item.get("id") or f"reference{index}"
    candidate = str(identity)
    return candidate if _SAFE_COMPONENT.fullmatch(candidate) else "ref" + hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:16]


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


def _ensure(path: Path, data: str | bytes) -> str:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    digest = hashlib.sha256(payload).hexdigest()
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        return _write(path, payload)
    return digest


def _trace_markdown(claim_ids: list[Any], claims: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]]) -> str:
    lines = ["## Evidence trace"]
    for claim_id in claim_ids:
        for ref in claims[str(claim_id)]["evidence_refs"]:
            evidence_id = ref if isinstance(ref, str) else ref["evidence_id"]
            item = evidence[str(evidence_id)]
            lines.append(f"- claim `{claim_id}`; evidence `{evidence_id}`; document `{item['document_id']}`; version `{item['version_id']}`; locator `{item['locator']}`")
    return "\n".join(lines)

def _monitor_rows(monitor: dict[str, Any] | None) -> tuple[list[str], list[list[str]]]:
    if not monitor: return [], []
    cycle=monitor.get("cycle", {}); profile=monitor.get("profile", {}); coverage=cycle.get("coverage", {})
    summary=[f"Window: {cycle.get('window_start','')} to {cycle.get('window_end','')}", f"Rule: {cycle.get('rule_version',profile.get('rule_version',''))}", f"Collection: {cycle.get('status','')}; complete={cycle.get('complete',False)}; backlog={len(cycle.get('judgment_backlog',[]))}; coverage={json.dumps(coverage,ensure_ascii=False,sort_keys=True)}"]
    rows=[]
    for issue in monitor.get("review_issues", []):
        effective=issue.get("effective_judgment", {})
        rows.append([str(issue.get("document_id","")), str(next((d.get("document_version","") for d in cycle.get("documents",[]) if d.get("document_id")==issue.get("document_id")),"")), str(effective.get("relevance","")), str(effective.get("human_review_required",False)), str(effective.get("reason","")), str(issue.get("status",""))])
    return summary, rows


def _render_markdown(kind: str, sections: list[dict[str, Any]], claims: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]], synthetic: bool, monitor: dict[str, Any] | None = None) -> str:
    parts = [f"# {kind}"]
    if synthetic:
        parts.append("> **SYNTHETIC REPORT — test/replay data only.**")
    if kind == "patent_monitor_digest" and monitor:
        summary, rows=_monitor_rows(monitor); table=["| document | version | relevance | human review | reason | status |","|---|---|---|---|---|---|"] + ["| " + " | ".join(row) + " |" for row in rows]
        parts.append("## Monitor facts\n" + "\n".join(summary + table))
    for section in sections:
        parts.extend((f"## {section['title']}", section["body"]))
    parts.append(_trace_markdown([claim for section in sections for claim in section.get("claim_ids", [])], claims, evidence))
    return "\n\n".join(parts) + "\n"


def _render_html(kind: str, language: str, sections: list[dict[str, Any]], claims: dict[str, dict[str, Any]], evidence: dict[str, dict[str, Any]], synthetic: bool, monitor: dict[str, Any] | None = None) -> str:
    notice = "<p><strong>SYNTHETIC REPORT — test/replay data only.</strong></p>" if synthetic else ""
    body = "".join(f"<section><h2>{html.escape(section['title'])}</h2><p>{'<br>'.join(html.escape(line) for line in section['body'].splitlines())}</p></section>" for section in sections)
    trace = []
    for claim_id in [claim for section in sections for claim in section.get("claim_ids", [])]:
        for ref in claims[str(claim_id)]["evidence_refs"]:
            evidence_id = ref if isinstance(ref, str) else ref["evidence_id"]
            item = evidence[str(evidence_id)]
            trace.append(f"<li>claim <code>{html.escape(str(claim_id))}</code>; evidence <code>{html.escape(str(evidence_id))}</code>; document <code>{html.escape(str(item['document_id']))}</code>; version <code>{html.escape(str(item['version_id']))}</code>; locator <code>{html.escape(str(item['locator']))}</code></li>")
    if kind == "patent_monitor_digest" and monitor:
        summary, rows=_monitor_rows(monitor); facts="<h2>Monitor facts</h2><p>"+"<br>".join(html.escape(item) for item in summary)+"</p><table><tr><th>document</th><th>version</th><th>relevance</th><th>human review</th><th>reason</th><th>status</th></tr>"+"".join("<tr>"+"".join(f"<td>{html.escape(value)}</td>" for value in row)+"</tr>" for row in rows)+"</table>"
    else: facts=""
    return f"<!doctype html><html lang=\"{html.escape(language, quote=True)}\"><body><h1>{html.escape(kind)}</h1>{notice}{facts}{body}<h2>Evidence trace</h2><ul>{''.join(trace)}</ul></body></html>"


def _csv_text(rows: list[list[Any]]) -> str:
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerows([[_safe_csv(value) for value in row] for row in rows])
    return handle.getvalue()


def _bibtex(items: list[dict[str, Any]]) -> str:
    entries: list[str] = []
    keys: set[str] = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"]:
            raise ValidationError("bibliography item needs a title")
        key = _citation_key(item, index)
        kind = "article" if item.get("type") == "review" else item.get("type", "article")
        if kind not in {"article", "book", "incollection", "inproceedings", "manual", "misc", "phdthesis", "techreport", "unpublished"} or not _SAFE_COMPONENT.fullmatch(key) or key in keys:
            raise ValidationError("bibliography has invalid BibTeX type or key")
        allowed = {"author", "title", "journal", "booktitle", "year", "volume", "number", "pages", "publisher", "doi", "url", "note", "month", "edition", "institution", "citation_key", "id", "type"}
        provenance_only = {"visibility"}
        if set(item) - allowed - provenance_only:
            raise ValidationError("bibliography has unsupported BibTeX field")
        keys.add(key)
        fields = [(key, value) for key, value in item.items() if key not in {"citation_key", "id", "type", *provenance_only} and value not in (None, "")]
        rendered = ",\n  ".join(f"{name} = {{{_bib(value)}}}" for name, value in fields)
        entries.append(f"@{kind}{{{_bib(key)},\n  {rendered}\n}}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def _targets(data: dict[str, Any], sections: list[dict[str, Any]], languages: list[str] | None) -> list[tuple[str, list[str]]]:
    declared = data.get("report_targets")
    if declared is None:  # Compatibility: report only types actually supplied, never all possible types.
        declared = [{"deliverable_type": s.get("deliverable_type"), "languages": [s.get("language")]} for s in sections]
    if not isinstance(declared, list) or not declared:
        raise ValidationError("report_targets must be a non-empty list")
    result: dict[str, list[str]] = {}
    for item in declared:
        kind = item if isinstance(item, str) else item.get("deliverable_type") if isinstance(item, dict) else None
        target_languages = [] if isinstance(item, str) else item.get("languages", [])
        if kind not in _TYPES or not isinstance(target_languages, list):
            raise ValidationError("invalid report target")
        raw_languages = languages if languages is not None else (target_languages or [s.get("language") for s in sections if s.get("deliverable_type") == kind])
        safe = [_component(language, "language") for language in raw_languages if language]
        if not safe:
            raise ValidationError("report target has no safe language")
        result.setdefault(kind, [])
        result[kind].extend(language for language in safe if language not in result[kind])
    return list(result.items())


def export_reports(workspace: str | Path, run_id: str, report_data: dict[str, Any], languages: list[str] | None = None) -> dict[str, Any]:
    """Export supplied frozen facts without network, model, database, or translation."""
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
    evidence_items = report_data.get("evidence")
    claims_items = report_data.get("claims", [])
    sections = report_data.get("sections")
    if not all(isinstance(value, list) for value in (evidence_items, claims_items, sections)):
        raise ValidationError("evidence, claims and sections must be lists")
    if not all(isinstance(item, dict) for item in [*evidence_items, *claims_items, *sections]):
        raise ValidationError("evidence, claims and sections must contain objects")
    evidence_ids = [item.get("evidence_id") for item in evidence_items]
    claim_ids = [item.get("claim_id") for item in claims_items]
    if not all(evidence_ids) or len(evidence_ids) != len(set(evidence_ids)) or not all(claim_ids) or len(claim_ids) != len(set(claim_ids)):
        raise ValidationError("evidence_id and claim_id must be unique")
    evidence = {str(item["evidence_id"]): item for item in evidence_items}
    claims = {str(item["claim_id"]): item for item in claims_items}
    targets = _targets(report_data, sections, languages)
    fingerprint = _digest(report_data)
    canonical_path = target / "report-data.canonical.json"
    manifest_path = target / "export-manifest.json"
    canonical = {"kind": "frozen_report_data", "report_data_sha256": fingerprint, "report_data": report_data}
    if canonical_path.exists() and json.loads(canonical_path.read_text(encoding="utf-8")).get("report_data_sha256") != fingerprint:
        raise ReportExportError("refusing to overwrite a frozen report version with different facts")
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prior.get("report_data_sha256") != fingerprint:
            raise ReportExportError("refusing to overwrite a frozen report version with different facts")
        prior_targets = prior.get("requested_targets", [])
        merged = {kind: list(target_languages) for kind, target_languages in targets}
        for item in prior_targets:
            kind = item.get("deliverable_type")
            if kind in _TYPES:
                merged.setdefault(kind, [])
                merged[kind].extend(language for language in item.get("languages", []) if language not in merged[kind])
        targets = list(merged.items())
    issues = list(report_data.get("issues") or [])
    artifacts: list[dict[str, Any]] = [_artifact(canonical_path, root, "canonical", version, None, "canonical_json", _ensure(canonical_path, json.dumps(canonical, ensure_ascii=False, indent=2) + "\n"))]

    for kind, target_languages in targets:
        for language in target_languages:
            matching = [s for s in sections if isinstance(s, dict) and s.get("deliverable_type") == kind and s.get("language") == language]
            if not matching:
                issues.append({"code": "RH_REPORT_LANGUAGE_MISSING", "type": kind, "language": language, "message": "no supplied body for requested target"})
                continue
            invalid = []
            for section in matching:
                factual = section.get("section_kind", "scientific") not in {"context", "method", "administrative"}
                if not isinstance(section.get("section_id"), str) or not isinstance(section.get("title"), str) or not isinstance(section.get("body"), str) or not section["body"] or not isinstance(section.get("claim_ids", []), list) or (factual and not section.get("claim_ids")):
                    invalid.append({"section_id": section.get("section_id"), "reason": "scientific body lacks valid claim_ids"})
                    continue
                for claim_id in section.get("claim_ids", []):
                    claim = claims.get(str(claim_id))
                    okay, reason = _claim_ok(claim, evidence) if claim else (False, "unknown claim")
                    if not okay:
                        invalid.append({"section_id": section["section_id"], "claim_id": claim_id, "reason": reason})
            if invalid:
                issues.append({"code": "RH_REPORT_CITATION_INVALID", "type": kind, "language": language, "sections": invalid})
                continue
            markdown_path, html_path = target / f"{kind}.{language}.md", target / f"{kind}.{language}.html"
            artifacts.append(_artifact(markdown_path, root, kind, version, language, "markdown", _ensure(markdown_path, _render_markdown(kind, matching, claims, evidence, bool(report_data["synthetic"]), report_data.get("monitor")))) )
            artifacts.append(_artifact(html_path, root, kind, version, language, "html", _ensure(html_path, _render_html(kind, language, matching, claims, evidence, bool(report_data["synthetic"]), report_data.get("monitor")))) )

    comparison_rows = [["finding_id", "value", "unit", "conditions", "evidence_refs"]]
    for item in report_data.get("findings", []):
        if isinstance(item, dict): comparison_rows.append([item.get("finding_id", ""), item.get("value", ""), item.get("unit", ""), item.get("conditions", ""), json.dumps(item.get("evidence_refs", []), ensure_ascii=False)])
    comparison_path = target / "comparison.csv"
    artifacts.append(_artifact(comparison_path, root, "comparison", version, None, "comparison_csv", _ensure(comparison_path, _csv_text(comparison_rows))))
    review_rows = [["issue_id", "document_id", "status", "relevance", "human_review_required", "reason"]]
    for item in (report_data.get("monitor") or {}).get("review_issues", []):
        effective=item.get("effective_judgment", {})
        review_rows.append([item.get("issue_id", ""), item.get("document_id", ""), item.get("status", ""), effective.get("relevance", ""), effective.get("human_review_required", ""), effective.get("reason", "")])
    for item in issues:
        if isinstance(item, dict): review_rows.append([item.get("issue_id", ""), item.get("status", "open"), item.get("message", item.get("reason", "")), json.dumps(item.get("claim_ids", item.get("claims", [])), ensure_ascii=False)])
    review_path = target / "human-review.csv"
    artifacts.append(_artifact(review_path, root, "human_review", version, None, "review_csv", _ensure(review_path, _csv_text(review_rows))))
    bib_path = target / "bibliography.bib"
    artifacts.append(_artifact(bib_path, root, "bibliography", version, None, "bibtex", _ensure(bib_path, _bibtex(report_data.get("bibliography", [])))))
    status = "partial" if issues else "completed"
    manifest = {"run_id": run, "report_version": version, "report_data_sha256": fingerprint, "requested_targets": [{"deliverable_type": kind, "languages": target_languages} for kind, target_languages in targets], "artifacts": artifacts, "status": status, "issues": issues}
    _ensure(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {key: manifest[key] for key in ("run_id", "report_version", "artifacts", "status", "issues")}
