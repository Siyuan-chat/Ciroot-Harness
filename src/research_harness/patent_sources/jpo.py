"""JPO domestic and OPD adapters, pinned to the frozen official OpenAPI paths."""
from __future__ import annotations

import os
import re
from urllib.parse import quote
from typing import Any
from xml.etree import ElementTree

from .contracts import SourceContext, SourceFailure, failed, parse_json_body, pending, request_once, response_status, result


DOMESTIC_BASE = "https://ip-data.jpo.go.jp/api"
OPD_BASE = "https://ip-data.jpo.go.jp/opdapi"
SPEC_VERSION = "JPO OpenAPI 1.0 / OpenAPI 3.0.0"
APP = r"[0-9]{10}"
APPLICANT_CODE = r"[0-9]{9}"
OPD_REFERENCE = r"[A-Za-z]{2}\.[0-9]{1,94}\.[A-Za-z0-9*]{1,2}"

# Each entry corresponds to one of the 20 /patent/v1 paths in the frozen JPO
# OpenAPI: 14 domestic operations and 6 OPD operations.
OPERATIONS = {
    "app_progress": ("domestic", "case_progress", "/patent/v1/app_progress/{application_number}", "application_number"),
    "app_progress_simple": ("domestic", "case_progress", "/patent/v1/app_progress_simple/{application_number}", "application_number"),
    "divisional_app_info": ("domestic", "case_relation", "/patent/v1/divisional_app_info/{application_number}", "application_number"),
    "priority_right_app_info": ("domestic", "case_relation", "/patent/v1/priority_right_app_info/{application_number}", "application_number"),
    "applicant_attorney_by_code": ("domestic", "party_reference", "/patent/v1/applicant_attorney_cd/{applicant_code}", "applicant_code"),
    "applicant_attorney_by_name": ("domestic", "party_reference", "/patent/v1/applicant_attorney/{applicant_name}", "applicant_name"),
    "case_number_reference": ("domestic", "number_conversion", "/patent/v1/case_number_reference/{case_type}/{case_number}", "case_number"),
    "application_documents": ("domestic", "application_documents", "/patent/v1/app_doc_cont_opinion_amendment/{application_number}", "application_number"),
    "dispatch_documents": ("domestic", "application_documents", "/patent/v1/app_doc_cont_refusal_reason_decision/{application_number}", "application_number"),
    "refusal_reason_documents": ("domestic", "application_documents", "/patent/v1/app_doc_cont_refusal_reason/{application_number}", "application_number"),
    "cite_doc_info": ("domestic", "citation_lookup", "/patent/v1/cite_doc_info/{application_number}", "application_number"),
    "registration_info": ("domestic", "registration_lookup", "/patent/v1/registration_info/{application_number}", "application_number"),
    "jpp_fixed_address": ("domestic", "case_reference", "/patent/v1/jpp_fixed_address/{application_number}", "application_number"),
    "pct_national_phase_application_number": ("domestic", "number_conversion", "/patent/v1/pct_national_phase_application_number/{case_type}/{case_number}", "case_number"),
    "opd_family": ("opd", "family_lookup", "/patent/v1/family/{case_type}/{case_reference}", "case_reference"),
    "opd_family_list": ("opd", "family_lookup", "/patent/v1/family_list/{case_type}/{case_reference}", "case_reference"),
    "opd_global_doc_list": ("opd", "case_progress", "/patent/v1/global_doc_list/{case_reference}", "case_reference"),
    "opd_global_cite_class": ("opd", "citation_lookup", "/patent/v1/global_cite_class/{case_reference}", "case_reference"),
    "opd_global_doc_content": ("opd", "application_documents", "/patent/v1/global_doc_cont/{case_reference}/{document_id}", "document_id"),
    "opd_jp_doc_content": ("opd", "application_documents", "/patent/v1/jp_doc_cont/{case_reference}/{document_id}", "document_id"),
}


def _validate_params(operation: str, params: dict[str, Any]) -> dict[str, str]:
    if not isinstance(params, dict):
        raise SourceFailure("error", "RH_JPO_PARAMS", "params must be an object")
    required = {
        "application_number": APP,
        "applicant_code": APPLICANT_CODE,
        "applicant_name": r"[^\t,:|]+",
        "case_number": r"[^\t,:|]+",
        "case_reference": OPD_REFERENCE,
        "document_id": r"[A-Za-z0-9_.-]{1,160}",
    }
    route = OPERATIONS[operation][2]
    keys = re.findall(r"\{([^}]+)\}", route)
    param_names = {"application_number", "applicant_code", "applicant_name", "case_number", "case_reference", "document_id", "case_type"}
    normalized: dict[str, str] = {}
    for key in keys:
        value = params.get(key)
        if not isinstance(value, str) or not value:
            raise SourceFailure("error", "RH_JPO_PARAMS", f"{key} must be a non-empty string")
        if key in required and not re.fullmatch(required[key], value):
            raise SourceFailure("error", "RH_JPO_PARAMS", f"{key} does not match the frozen JPO format")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise SourceFailure("error", "RH_JPO_PARAMS", f"{key} contains control characters")
        if key == "case_type":
            allowed = {"application", "publication", "registration"} if operation == "case_number_reference" else {"international_application", "international_publication"} if operation == "pct_national_phase_application_number" else {"application", "publication"}
            if value not in allowed:
                raise SourceFailure("error", "RH_JPO_PARAMS", "case_type is not allowed for this operation")
        normalized[key] = value
    if set(params) - param_names:
        raise SourceFailure("error", "RH_JPO_PARAMS", "unexpected JPO path parameter")
    return normalized


class JPOAdapter:
    source = "jpo"

    def __init__(self, context: SourceContext, *, enabled: bool, token_env: str, opd_enabled: bool = False):
        self.context, self.enabled, self.token_env, self.opd_enabled = context, enabled, token_env, opd_enabled

    def execute(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(operation, str) or not operation:
            return pending(self.source, "", "error", "RH_JPO_OPERATION", "operation must be a non-empty string")
        if operation == "keyword_search":
            return pending(self.source, operation, "unsupported", "RH_JPO_NO_KEYWORD_SEARCH", "JPO OpenAPI has no general keyword-search endpoint", "exact_identifier_lookup")
        if operation not in OPERATIONS:
            return pending(self.source, operation, "pending_spec", "RH_JPO_OPERATION_UNVERIFIED", "operation is not in the frozen 20-path patent contract")
        server, capability, route, _ = OPERATIONS[operation]
        denied = self._activation(operation, server, capability)
        if denied:
            return denied
        unsupported = pending(self.source, operation, "unsupported", "RH_PATENT_CAPABILITY", "required capability was not granted", capability) if capability not in self.context.capabilities else None
        if unsupported:
            return unsupported
        meta = None
        try:
            path_params = _validate_params(operation, params)
            path = route.format(**{key: quote(value, safe="") for key, value in path_params.items()})
            base = OPD_BASE if server == "opd" else DOMESTIC_BASE
            url = base + path
            token = os.environ.get(self.token_env, "")
            max_bytes = self.context.max_response_bytes
            status_code, headers, body, meta = request_once(
                self.context, source=self.source, operation=operation, capability=capability, method="GET", url=url,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json, application/zip, application/xml"},
                max_bytes=max_bytes, allowed_hosts=("ip-data.jpo.go.jp",),
                allowed_path_prefixes=("/api/patent/v1/", "/opdapi/patent/v1/"),
                accept="application/json, application/zip, application/xml", sensitive_headers=("Authorization",),
            )
            status = response_status(self.source, operation, status_code)
            if status:
                return failed(self.source, operation, status, f"RH_JPO_HTTP_{status_code}", f"JPO returned HTTP {status_code}", capability, meta, SPEC_VERSION)
            content_type = headers.get("content-type", "").casefold()
            media = content_type.split(";", 1)[0].strip()
            if not body:
                return failed(self.source, operation, "error", "RH_JPO_EMPTY_BODY", "JPO returned an empty response body", capability, meta, SPEC_VERSION)
            binary_type = "application/zip" if operation in {"application_documents", "dispatch_documents", "refusal_reason_documents", "opd_jp_doc_content"} else "application/pdf"
            if operation in {"application_documents", "dispatch_documents", "refusal_reason_documents"}:
                allowed_types = {"application/json", "application/zip"}
            elif operation == "opd_global_doc_content":
                allowed_types = {"application/json", "application/xml", "application/pdf"}
            elif operation == "opd_jp_doc_content":
                allowed_types = {"application/json", "application/xml", "application/zip"}
            else:
                allowed_types = {"application/json", "application/xml"} if server == "opd" else {"application/json"}
            if media not in allowed_types:
                return failed(self.source, operation, "error", "RH_JPO_CONTENT_TYPE", "JPO response content type is not allowed for this operation", capability, meta, SPEC_VERSION)
            if media == "application/json":
                data = parse_json_body(body, content_type)
                business = data.get("result", {}).get("statusCode") if isinstance(data, dict) and isinstance(data.get("result"), dict) else None
                if not isinstance(business, str) or not re.fullmatch(r"[0-9]{3}", business):
                    return failed(self.source, operation, "partial", "RH_JPO_STATUS_MISSING", "JPO JSON response is missing its documented result.statusCode", capability, meta, SPEC_VERSION)
                if str(business) == "107":
                    return result(self.source, operation, capability, "no_match", data, {"complete": True, "partial": False}, [{**meta, "spec_version": SPEC_VERSION}])
                if str(business) == "203":
                    return failed(self.source, operation, "rate_limited", "RH_JPO_DAILY_LIMIT", "JPO business response reports the daily API limit", capability, meta, SPEC_VERSION)
                if business is not None and str(business) != "100":
                    return failed(self.source, operation, "error", f"RH_JPO_BUSINESS_{business}", "JPO business response is not a success status", capability, meta, SPEC_VERSION)
                payload = data.get("result", {}).get("data")
                if not isinstance(payload, dict):
                    return failed(self.source, operation, "partial", "RH_JPO_DATA_MISSING", "JPO success response lacks its documented result.data object", capability, meta, SPEC_VERSION)
            elif media == "application/xml":
                try:
                    root = ElementTree.fromstring(body)
                except ElementTree.ParseError as exc:
                    raise SourceFailure("error", "RH_JPO_INVALID_XML", "JPO XML response is not well formed") from exc
                status_node = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "statusCode"), None)
                business = status_node.text.strip() if status_node is not None and status_node.text else None
                data = {"format": "xml", "root_tag": root.tag.rsplit("}", 1)[-1], "status_code": business, "content": body}
                if business == "107":
                    return result(self.source, operation, capability, "no_match", data, {"complete": True, "partial": False}, [{**meta, "spec_version": SPEC_VERSION}])
                if business == "203":
                    return failed(self.source, operation, "rate_limited", "RH_JPO_DAILY_LIMIT", "JPO business response reports the daily API limit", capability, meta, SPEC_VERSION)
                if business is not None and business != "100":
                    return failed(self.source, operation, "error", f"RH_JPO_BUSINESS_{business}", "JPO business response is not a success status", capability, meta, SPEC_VERSION)
                if root.tag.rsplit("}", 1)[-1] != "api-data":
                    return failed(self.source, operation, "error", "RH_JPO_XML_ROOT", "JPO XML response has an unexpected root element", capability, meta, SPEC_VERSION)
                if business == "100" and len(root) <= 1:
                    return failed(self.source, operation, "partial", "RH_JPO_DATA_MISSING", "JPO XML success response lacks operation data", capability, meta, SPEC_VERSION)
                if business is None and (server != "opd" or not any(node.tag.rsplit("}", 1)[-1] not in {"errorMessage", "remainAccessCount"} for node in root)):
                    return failed(self.source, operation, "partial", "RH_JPO_STATUS_MISSING", "JPO XML response lacks status and recognizable OPD data", capability, meta, SPEC_VERSION)
            elif media == binary_type:
                magic_ok = body.startswith(b"%PDF-") if media == "application/pdf" else body.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
                if not magic_ok:
                    return failed(self.source, operation, "error", "RH_JPO_BINARY_SIGNATURE", "JPO document does not match its declared PDF/ZIP format", capability, meta, SPEC_VERSION)
                data = {"format": "pdf" if media == "application/pdf" else "zip", "content": body}
            else:
                return failed(self.source, operation, "error", "RH_JPO_CONTENT_TYPE", "JPO response format is not supported", capability, meta, SPEC_VERSION)
            return result(self.source, operation, capability, "complete", data, {"complete": True, "partial": False}, [{**meta, "spec_version": SPEC_VERSION}])
        except SourceFailure as exc:
            return failed(self.source, operation, exc.status, exc.code, exc.message, capability, meta, SPEC_VERSION)

    def _activation(self, operation: str, server: str, capability: str) -> dict[str, Any] | None:
        if self.enabled is not True:
            return pending(self.source, operation, "pending_activation", "RH_JPO_DISABLED", "JPO connector is not enabled", capability)
        if server == "opd" and self.opd_enabled is not True:
            return pending(self.source, operation, "pending_activation", "RH_JPO_OPD_PERMISSION", "OPD permission is not activated for this profile", capability)
        if not isinstance(self.token_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.token_env):
            return pending(self.source, operation, "pending_activation", "RH_JPO_TOKEN_ENV", "configured JPO token environment variable name is invalid", capability)
        if not os.environ.get(self.token_env):
            return pending(self.source, operation, "pending_activation", "RH_JPO_TOKEN_MISSING", "configured JPO bearer token is unavailable", capability)
        return None
