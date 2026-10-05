"""USPTO Open Data Portal connector using only the injected core transport."""
from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

from .contracts import SourceContext, SourceFailure, failed, parse_json_body, pending, request_once, response_status, result


BASE = "https://api.uspto.gov"
SOURCE = "uspto_odp"
SPEC_VERSION = "USPTO ODP OpenAPI 1.0.0; frozen local uspto-openapi.yaml/uspto-common.yaml"
SPEC_URL = "https://data.uspto.gov/swagger/swagger.yaml"
SPEC_EVIDENCE = {
    "official_openapi_url": SPEC_URL,
    "frozen_files": {
        "uspto-openapi.yaml": "sha256:6c01165869e2c806969281baea75daaa84caf3b4db038cb4cc5246366e2f4f32",
        "uspto-common.yaml": "sha256:b793469a103afd78cc72c3ca3a41a4673588cf56a0b178f0d23b2974bb36121c",
        "uspto-patent-schema.json": "sha256:be366c89dea49ca3bd06b0ca1826a49c3d47336b947fb38cc61b08c1bb6e24b0",
        "uspto-documents-sample.md": "sha256:9582777f28ac1189bebc1eb7b4cbf2bcf29949ed1d2d025a346a0d085e8c6100",
        "uspto-associated-documents-sample.md": "sha256:136df19afd1d544e8c3455781da5ae9e4b7ec72bcee274b3bb15a73066d6873c",
        "uspto-application-data-sample.md": "sha256:8895479e227a728c55afecea6bd7914f0c0dc6dcb6091c3ea22e31fe47b59c9b",
    },
}
APP_NUMBER = re.compile(r"(?:[0-9]{2,8}|PCT/[A-Z]{2}[0-9]{2}/[0-9]{6}|PCT[A-Z]{2}[0-9]{7})", re.I)
GET_SEARCH_FIELDS = {"q", "sort", "offset", "limit", "facets", "fields", "filters", "rangeFilters"}
POST_SEARCH_FIELDS = {"q", "filters", "rangeFilters", "sort", "fields", "pagination", "facets"}
EXPECTED_TYPES = {
    "application_details": {"applicationMetaData": dict}, "metadata": {"applicationMetaData": dict},
    "adjustment": {"patentTermAdjustmentData": dict}, "assignment": {"assignmentBag": list},
    "attorney": {"recordAttorney": dict}, "continuity": {"parentContinuityBag": list, "childContinuityBag": list},
    "foreign_priority": {"foreignPriorityBag": list}, "transactions": {"eventDataBag": list},
    "documents": {"documentBag": list}, "associated_documents": {"pgpubDocumentMetaData": dict, "grantDocumentMetaData": dict},
}
ROUTES = {
    "application_details": "/api/v1/patent/applications/{app}",
    "metadata": "/api/v1/patent/applications/{app}/meta-data",
    "adjustment": "/api/v1/patent/applications/{app}/adjustment",
    "assignment": "/api/v1/patent/applications/{app}/assignment",
    "attorney": "/api/v1/patent/applications/{app}/attorney",
    "continuity": "/api/v1/patent/applications/{app}/continuity",
    "foreign_priority": "/api/v1/patent/applications/{app}/foreign-priority",
    "transactions": "/api/v1/patent/applications/{app}/transactions",
    "documents": "/api/v1/patent/applications/{app}/documents",
    "associated_documents": "/api/v1/patent/applications/{app}/associated-documents",
}
DOWNLOAD_PREFIXES = ("/api/v1/download/applications/", "/api/v1/patent/application/documents/", "/api/v1/datasets/products/files/")
DEFAULT_DOWNLOAD_HOSTS = ("api.uspto.gov", "bulkdata.uspto.gov", "assignmentcenter.uspto.gov", "legacy-assignments.uspto.gov")


class USPTOAdapter:
    def __init__(self, context: SourceContext, *, enabled: bool, api_key_env: str = "USPTO_ODP_API_KEY",
                 download_hosts: tuple[str, ...] = DEFAULT_DOWNLOAD_HOSTS):
        self.context, self.enabled, self.api_key_env = context, enabled, api_key_env
        if not isinstance(download_hosts, tuple) or any(not isinstance(host, str) or not host for host in download_hosts):
            raise ValueError("download_hosts must be a tuple of configured hostnames")
        self.download_hosts = download_hosts

    def execute(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(operation, str) or not operation:
            return pending(SOURCE, "", "error", "RH_USPTO_OPERATION", "operation must be a non-empty string")
        capability = "patent_search" if operation in {"search_get", "search_post"} else "application_record"
        if operation not in {"search_get", "search_post", *ROUTES}:
            return pending(SOURCE, operation, "pending_spec", "RH_USPTO_OPERATION_PENDING", "operation is not in the frozen ODP contract")
        activation = self._activation(operation, capability)
        if activation:
            return activation
        if not isinstance(params, dict):
            return pending(SOURCE, operation, "error", "RH_USPTO_PARAMS", "params must be an object", capability)
        meta = None
        try:
            method, path, query, body, offset, limit = self._request_parts(operation, params)
            response_headers = {"Accept": "application/json", "X-API-KEY": os.environ[self.api_key_env]}
            if method == "POST":
                response_headers["Content-Type"] = "application/json"
            status_code, headers, raw, meta = request_once(
                self.context, source=SOURCE, operation=operation, capability=capability, method=method,
                url=BASE + path, headers=response_headers, params=query, body=body,
                max_bytes=self.context.max_response_bytes, allowed_hosts=("api.uspto.gov",),
                allowed_path_prefixes=("/api/v1/patent/",), accept="application/json", sensitive_headers=("X-API-KEY",),
            )
            status = response_status(SOURCE, operation, status_code)
            if status:
                return failed(SOURCE, operation, status, f"RH_USPTO_HTTP_{status_code}", f"USPTO ODP returned HTTP {status_code}", capability, meta, SPEC_VERSION)
            if not raw:
                return failed(SOURCE, operation, "partial", "RH_USPTO_EMPTY_BODY", "USPTO returned an empty success body", capability, meta, SPEC_VERSION)
            if headers.get("content-type", "").split(";", 1)[0].strip().casefold() != "application/json":
                return failed(SOURCE, operation, "error", "RH_USPTO_CONTENT_TYPE", "USPTO ODP response is not application/json", capability, meta, SPEC_VERSION)
            data = parse_json_body(raw, headers.get("content-type", ""))
            if not isinstance(data, dict):
                return failed(SOURCE, operation, "partial", "RH_USPTO_SCHEMA", "USPTO success body root must be an object", capability, meta, SPEC_VERSION)
            valid, records, record_key = _validate_response(operation, data)
            if not valid:
                return failed(SOURCE, operation, "partial", "RH_USPTO_SCHEMA", "USPTO success body is missing documented response fields or has invalid types", capability, meta, SPEC_VERSION)
            response_count = data.get("count")
            projection = [_project_record(item) for item in records]
            if operation == "documents" and response_count != len(records):
                issues = [{"code": "RH_USPTO_COUNT_MISMATCH", "message": "documents count does not equal documentBag length"}]
            else:
                issues = []
            if response_count == 0 and not records and (operation not in {"search_get", "search_post"} or offset == 0):
                return result(SOURCE, operation, capability, "no_match", {"raw": data, "records": [], "record_key": record_key},
                              {"complete": not issues, "partial": bool(issues), "offset": offset, "limit": limit, "returned_count": 0, "reported_count": response_count},
                              [{**meta, "spec_version": SPEC_VERSION, "spec_evidence": SPEC_EVIDENCE}])
            if operation in {"search_get", "search_post"}:
                coverage: dict[str, Any] = {"complete": False, "partial": True, "offset": offset, "limit": limit,
                                            "returned_count": len(records), "reported_count": response_count,
                                            "reported_count_semantics": "unspecified_by_frozen_schema"}
                if len(records) >= limit:
                    coverage["next_offset"] = offset + len(records)
                    issues.append({"code": "RH_USPTO_PAGE_TRUNCATED", "message": "page reached requested limit; resume at next_offset"})
                else:
                    issues.append({"code": "RH_USPTO_TOTAL_UNCONFIRMED", "message": "ODP frozen schema does not define count as a total; page end cannot establish complete query coverage"})
                _add_identity_issues(records, projection, issues)
            else:
                coverage = {"complete": not issues, "partial": bool(issues), "returned_count": len(records),
                            "reported_count": response_count}
                if record_key in {"patentFileWrapperDataBag", "documentBag"}:
                    _check_requested_identity(params.get("application_number"), records, projection, issues,
                                              unique_key="documentIdentifier" if record_key == "documentBag" else "applicationNumberText")
                if response_count == 0 and records:
                    issues.append({"code": "RH_USPTO_COUNT_MISMATCH", "message": "response reports zero records but includes record data"})
                if issues:
                    coverage.update({"complete": False, "partial": True})
            result_data = {"raw": data, "records": projection, "record_key": record_key}
            if operation in {"search_get", "search_post"}:
                result_data["pagination"] = {"offset": offset, "limit": limit, "next_offset": coverage.get("next_offset")}
            return result(SOURCE, operation, capability, "partial" if coverage["partial"] else "complete", result_data, coverage,
                          [{**meta, "spec_version": SPEC_VERSION, "spec_evidence": SPEC_EVIDENCE}], issues)
        except SourceFailure as exc:
            return failed(SOURCE, operation, exc.status, exc.code, exc.message, capability, meta, SPEC_VERSION)

    def download_file(self, url: str) -> dict[str, Any]:
        operation, capability = "document_file", "document_download"
        if self.enabled is not True:
            return pending(SOURCE, operation, "pending_activation", "RH_USPTO_DISABLED", "USPTO connector is not enabled", capability)
        key = os.environ.get(self.api_key_env, "")
        if not key:
            return pending(SOURCE, operation, "pending_activation", "RH_USPTO_KEY_MISSING", "USPTO ODP API key environment variable is not set", capability)
        if capability not in self.context.capabilities:
            return pending(SOURCE, operation, "unsupported", "RH_PATENT_CAPABILITY", "document download capability was not granted", capability)
        try:
            parsed = urlsplit(url) if isinstance(url, str) and not any(ord(ch) < 32 or ord(ch) == 127 for ch in url) else None
        except ValueError:
            parsed = None
        if not _download_url_allowed(parsed, self.download_hosts):
            return pending(SOURCE, operation, "error", "RH_USPTO_DOWNLOAD_URL", "document URL host is outside the configured USPTO allowlist", capability)
        host_prefixes = {"api.uspto.gov": DOWNLOAD_PREFIXES, "bulkdata.uspto.gov": ("/data/patent/",),
                         "assignmentcenter.uspto.gov": ("/ipas/search/api/v2/public/download/patent/",),
                         "legacy-assignments.uspto.gov": ("/assignments/assignment-pat-",)}
        prefix = host_prefixes.get(parsed.hostname) if parsed.hostname in self.download_hosts else None
        if prefix is not None and not any(parsed.path.startswith(item) for item in prefix):
            prefix = None
        if prefix is None:
            return pending(SOURCE, operation, "error", "RH_USPTO_DOWNLOAD_URL", "document URL path is outside the official configured allowlist", capability)
        headers = {"Accept": "application/pdf, application/zip, application/xml, text/xml"}
        # API key is strictly origin-bound. Official bulk-data host downloads receive no API key.
        sensitive = ()
        if parsed.hostname == "api.uspto.gov":
            headers["X-API-KEY"] = key
            sensitive = ("X-API-KEY",)
        meta = None
        try:
            status_code, response_headers, raw, meta = request_once(
                self.context, source=SOURCE, operation=operation, capability=capability, method="GET", url=url,
                headers=headers, max_bytes=self.context.max_response_bytes, allowed_hosts=(parsed.hostname,),
                allowed_path_prefixes=prefix, accept=headers["Accept"], sensitive_headers=sensitive,
            )
            status = response_status(SOURCE, operation, status_code)
            if status:
                return failed(SOURCE, operation, status, f"RH_USPTO_HTTP_{status_code}", f"USPTO document host returned HTTP {status_code}", capability, meta, SPEC_VERSION)
            if not raw:
                return failed(SOURCE, operation, "partial", "RH_USPTO_EMPTY_BODY", "USPTO file response is empty", capability, meta, SPEC_VERSION)
            media = response_headers.get("content-type", "").split(";", 1)[0].casefold()
            valid = ((media == "application/pdf" and raw.startswith(b"%PDF-")) or
                     (media == "application/zip" and raw.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))) or
                     (media in {"application/xml", "text/xml"} and _valid_xml(raw)))
            if not valid:
                return failed(SOURCE, operation, "partial", "RH_USPTO_FILE_TYPE", "USPTO file body does not match a supported declared type/signature", capability, meta, SPEC_VERSION)
            return result(SOURCE, operation, capability, "complete", {"content_type": media, "content": raw},
                          {"complete": True, "partial": False}, [{**meta, "spec_version": SPEC_VERSION, "spec_evidence": SPEC_EVIDENCE}])
        except SourceFailure as exc:
            return failed(SOURCE, operation, exc.status, exc.code, exc.message, capability, meta, SPEC_VERSION)

    def _activation(self, operation: str, capability: str) -> dict[str, Any] | None:
        if self.enabled is not True:
            return pending(SOURCE, operation, "pending_activation", "RH_USPTO_DISABLED", "USPTO connector is not enabled", capability)
        if not os.environ.get(self.api_key_env):
            return pending(SOURCE, operation, "pending_activation", "RH_USPTO_KEY_MISSING", "USPTO ODP API key environment variable is not set", capability)
        if capability not in self.context.capabilities:
            return pending(SOURCE, operation, "unsupported", "RH_PATENT_CAPABILITY", "required capability was not granted", capability)
        return None

    @staticmethod
    def _request_parts(operation: str, params: dict[str, Any]):
        if operation == "search_get":
            if set(params) - GET_SEARCH_FIELDS:
                raise SourceFailure("error", "RH_USPTO_PARAMS", "GET search contains undocumented parameter names")
            query = _validate_search_get(params)
            offset, limit = query.get("offset", 0), query.get("limit", 25)
            return "GET", "/api/v1/patent/applications/search", query, None, offset, limit
        if operation == "search_post":
            if set(params) - POST_SEARCH_FIELDS:
                raise SourceFailure("error", "RH_USPTO_PARAMS", "POST search body contains undocumented fields")
            body, offset, limit = _validate_search_post(params)
            return "POST", "/api/v1/patent/applications/search", {}, json.dumps(body, separators=(",", ":")).encode("utf-8"), offset, limit
        if operation not in ROUTES or set(params) != {"application_number"}:
            raise SourceFailure("error", "RH_USPTO_PARAMS", "operation expects exactly application_number")
        app = params["application_number"]
        if not isinstance(app, str) or not APP_NUMBER.fullmatch(app) or any(c in app for c in "?#"):
            raise SourceFailure("error", "RH_USPTO_PARAMS", "application_number does not match documented free-format identifier examples")
        return "GET", ROUTES[operation].format(app=quote(app, safe="")), {}, None, 0, None


def _validate_search_get(params: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in params.items():
        if key in {"offset", "limit"}:
            minimum = 0 if key == "offset" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise SourceFailure("error", "RH_USPTO_PARAMS", f"{key} must be an integer >= {minimum}")
        elif not isinstance(value, str):
            raise SourceFailure("error", "RH_USPTO_PARAMS", f"GET {key} must be a string per ODP query schema")
        out[key] = value
    return out


def _validate_search_post(params: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    body = dict(params)
    if "q" in body and not isinstance(body["q"], str):
        raise SourceFailure("error", "RH_USPTO_PARAMS", "q must be a string")
    for key in ("fields", "facets"):
        if key in body and (not isinstance(body[key], list) or any(not isinstance(x, str) for x in body[key])):
            raise SourceFailure("error", "RH_USPTO_PARAMS", f"{key} must be an array of strings")
    for key in ("filters", "rangeFilters", "sort"):
        if key in body and not isinstance(body[key], list):
            raise SourceFailure("error", "RH_USPTO_PARAMS", f"{key} must be an array")
    if "filters" in body and any(not isinstance(x, dict) or set(x) - {"name", "value"} or not isinstance(x.get("name"), str) or not isinstance(x.get("value"), list) or any(not isinstance(v, str) for v in x["value"]) for x in body["filters"]):
        raise SourceFailure("error", "RH_USPTO_PARAMS", "filters must follow the documented {name,value[]} schema")
    for item in body.get("rangeFilters", []):
        if not isinstance(item, dict) or set(item) - {"field", "valueFrom", "valueTo"} or not all(isinstance(item.get(k), str) for k in ("field", "valueFrom", "valueTo")):
            raise SourceFailure("error", "RH_USPTO_PARAMS", "rangeFilters must follow the documented field/valueFrom/valueTo schema")
    for item in body.get("sort", []):
        if not isinstance(item, dict) or set(item) - {"field", "order"} or not isinstance(item.get("field"), str) or item.get("order") not in {"Asc", "asc", "Desc", "desc"}:
            raise SourceFailure("error", "RH_USPTO_PARAMS", "sort must follow the documented field/order schema")
    pagination = body.get("pagination", {})
    if not isinstance(pagination, dict) or set(pagination) - {"offset", "limit"}:
        raise SourceFailure("error", "RH_USPTO_PARAMS", "pagination must contain only offset and limit")
    offset, limit = pagination.get("offset", 0), pagination.get("limit", 25)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise SourceFailure("error", "RH_USPTO_PARAMS", "pagination offset/limit violate the documented schema")
    return body, offset, limit


def _validate_response(operation: str, data: dict[str, Any]) -> tuple[bool, list[dict[str, Any]], str]:
    if operation in {"search_get", "search_post"}:
        records = data.get("patentFileWrapperDataBag")
        count = data.get("count")
        if not isinstance(records, list) or isinstance(count, bool) or not isinstance(count, int) or count < 0 or any(not isinstance(x, dict) or not x for x in records):
            return False, [], "patentFileWrapperDataBag"
        return True, records, "patentFileWrapperDataBag"
    if operation == "documents":
        records, count = data.get("documentBag"), data.get("count")
        if (not isinstance(records, list) or isinstance(count, bool) or not isinstance(count, int) or count < 0 or
                any(not isinstance(x, dict) or not x for x in records)):
            return False, [], "documentBag"
        return True, records, "documentBag"
    records = data.get("patentFileWrapperDataBag")
    count = data.get("count")
    if isinstance(records, list) and isinstance(count, int) and not isinstance(count, bool) and count >= 0 and all(isinstance(item, dict) for item in records):
        types = EXPECTED_TYPES[operation]
        if not records:
            return True, records, "patentFileWrapperDataBag"
        for record in records:
            found = False
            for key, expected_type in types.items():
                if key in record:
                    if not isinstance(record[key], expected_type):
                        return False, [], "patentFileWrapperDataBag"
                    found = True
            if not found:
                return False, [], "patentFileWrapperDataBag"
        return True, records, "patentFileWrapperDataBag"
    return False, [], "patentFileWrapperDataBag"


def _project_record(record: dict[str, Any]) -> dict[str, Any]:
    app = record.get("applicationNumberText")
    metadata = record.get("applicationMetaData") if isinstance(record.get("applicationMetaData"), dict) else {}
    projection: dict[str, Any] = {}
    if isinstance(app, str):
        projection["application_number"] = app
    doc_id = record.get("documentIdentifier")
    if isinstance(doc_id, str):
        projection["document_id"] = doc_id
    for source_key, target_key in (("documentCode", "document_code"), ("documentCodeDescriptionText", "document_description"), ("officialDate", "official_date")):
        value = record.get(source_key)
        if isinstance(value, str):
            projection[target_key] = value
    if isinstance(record.get("downloadOptionBag"), list):
        projection["download_options"] = record["downloadOptionBag"]
    pub = metadata.get("earliestPublicationNumber")
    if isinstance(pub, str) and pub:
        projection["publication_number"] = pub
    patent_no = metadata.get("patentNumber")
    if isinstance(patent_no, str) and patent_no:
        projection["patent_number"] = patent_no
    for source_key, target_key in (("inventionTitle", "title"), ("filingDate", "filing_date"), ("grantDate", "grant_date")):
        value = metadata.get(source_key)
        if isinstance(value, str):
            projection[target_key] = value
    return projection


def _add_identity_issues(records: list[dict[str, Any]], projection: list[dict[str, Any]], issues: list[dict[str, str]]) -> None:
    seen: set[str] = set()
    duplicate = False
    insufficient = False
    unprojectable = False
    for record, normalized in zip(records, projection):
        identity = record.get("applicationNumberText")
        if isinstance(identity, str) and identity:
            if identity in seen:
                duplicate = True
            seen.add(identity)
        else:
            insufficient = True
        if not normalized:
            unprojectable = True
    if duplicate:
        issues.append({"code": "RH_USPTO_DUPLICATE_IDENTITY", "message": "search response contains repeated applicationNumberText values"})
    if insufficient:
        issues.append({"code": "RH_USPTO_IDENTITY_INSUFFICIENT", "message": "one or more search records do not expose applicationNumberText; raw data retained without inferred identity"})
    if unprojectable:
        issues.append({"code": "RH_USPTO_PROJECTION_EMPTY", "message": "one or more records have no recognized projection fields; raw data retained for review"})


def _check_requested_identity(requested: str | None, records: list[dict[str, Any]], projection: list[dict[str, Any]], issues: list[dict[str, str]], *, unique_key: str) -> None:
    if not records:
        return
    missing = False
    wrong = False
    duplicate = False
    seen: set[str] = set()
    for record in records:
        identity = record.get("applicationNumberText")
        if not isinstance(identity, str) or not identity:
            missing = True
        elif identity != requested:
            wrong = True
        unique_identity = record.get(unique_key)
        if isinstance(unique_identity, str) and unique_identity:
            if unique_identity in seen:
                duplicate = True
            seen.add(unique_identity)
    if wrong:
        issues.append({"code": "RH_USPTO_WRONG_IDENTITY", "message": "returned applicationNumberText differs from requested application_number"})
    if missing:
        issues.append({"code": "RH_USPTO_IDENTITY_INSUFFICIENT", "message": "response omitted applicationNumberText; raw data retained without inferred identity"})
    if duplicate:
        issues.append({"code": "RH_USPTO_DUPLICATE_IDENTITY", "message": "response repeats applicationNumberText values"})
    if any(not record for record in projection):
        issues.append({"code": "RH_USPTO_PROJECTION_EMPTY", "message": "response has no recognized projection fields; raw data retained for review"})


def _download_url_allowed(parsed, configured_hosts: tuple[str, ...]) -> bool:
    if parsed is None:
        return False
    try:
        invalid = (parsed.scheme != "https" or parsed.hostname not in configured_hosts or
            parsed.port not in (None, 443) or parsed.username is not None or parsed.password is not None or
            parsed.query or parsed.fragment or "\\" in parsed.path)
    except ValueError:
        return False
    if invalid:
        return False
    path = parsed.path
    for _ in range(3):
        path = unquote(path)
    return not any(part in {".", ".."} for part in path.split("/"))


def _valid_xml(raw: bytes) -> bool:
    try:
        root = ElementTree.fromstring(raw)
        return bool(root.tag)
    except ElementTree.ParseError:
        return False
