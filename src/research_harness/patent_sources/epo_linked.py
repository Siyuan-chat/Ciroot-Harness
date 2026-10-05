"""EPO Linked Open EP adapter for documented, known item/list paths only."""
from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import quote

from .contracts import SourceContext, SourceFailure, failed, parse_json_body, pending, request_once, response_status, result


BASE = "https://data.epo.org/linked-data"
SOURCE = "epo_linked"
KNOWN_PATHS = {
    "application": "/doc/application/{authority}/{application_number}.json",
    "publication": "/data/publication/{st3}/{publication_number}/{kind}/{publication_date}.json",
    "classification_cpc": "/def/cpc/{symbol}.json",
    "classification_ipc": "/def/ipc/{symbol}.json",
    "publications_by_date": "/data/publication/EP",
}
SPEC_REFERENCES = {
    "overview": "https://data.epo.org/linked-data/documentation/api-overview",
    "reference": "https://data.epo.org/linked-data/documentation/api-reference",
    "frozen_local_shells": {
        ".local/integration-20261005/specs/epo-linked-overview.html": "sha256:3fb7601a7c4a335dfef0030a7e3716b4db1f31effba1d9c02457484038b60f57",
        ".local/integration-20261005/specs/epo-linked-reference.html": "sha256:bdaf0d005de2123ba5e4c7f0676edc6759d70c9d1d96b4a486e1f6b4877e9b9c",
    },
    "reference_note": "The cached HTML files are JavaScript shells only; paths and date query keys above were cross-checked against the official published API reference. The local shell hashes are retained as retrieval provenance, not schema evidence.",
    "verified_paths": ("/doc/application/{st3Code}/{applicationNumber}",
                       "/data/publication/{st3Code}/{publicationNumber}/{pubKind}/{pubDate}",
                       "/def/cpc/{symbol}", "/def/ipc/{symbol}"),
    "date_query": {"path": "/data/publication/EP", "keys": ("min-publicationDate", "max-publicationDate", "_page", "_pageSize")},
}


class EPOLinkedAdapter:
    def __init__(self, context: SourceContext, *, enabled: bool):
        self.context, self.enabled = context, enabled

    def execute(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(operation, str) or not operation:
            return pending(SOURCE, "", "error", "RH_EPO_LINKED_OPERATION", "operation must be a non-empty string")
        if operation in {"legal_events", "legal_status", "legal_data"}:
            return pending(SOURCE, operation, "pending_spec", "RH_EPO_LINKED_LEGAL_PATH_PENDING", "frozen official Linked Open EP reference does not identify a legal-event endpoint path")
        caps = {"application": "application_record", "publication": "publication_record", "classification_cpc": "cpc_vocabulary",
                "classification_ipc": "ipc_vocabulary", "publications_by_date": "publication_date_filter"}
        if operation not in caps:
            return pending(SOURCE, operation, "pending_spec", "RH_EPO_LINKED_PATH_PENDING", "no frozen official path is registered for this operation")
        capability = caps[operation]
        if self.enabled is not True:
            return pending(SOURCE, operation, "pending_activation", "RH_EPO_LINKED_DISABLED", "Linked Open EP connector is not enabled", capability)
        if capability not in self.context.capabilities:
            return pending(SOURCE, operation, "unsupported", "RH_PATENT_CAPABILITY", "required capability was not granted", capability)
        if not isinstance(params, dict):
            return pending(SOURCE, operation, "error", "RH_EPO_LINKED_PARAMS", "params must be an object", capability)
        meta = None
        try:
            path, query, partial = self._request_parts(operation, params)
            url = BASE + path
            status_code, headers, body, meta = request_once(
                self.context, source=SOURCE, operation=operation, capability=capability, method="GET", url=url,
                params=query, headers={"Accept": "application/json"}, accept="application/json",
                max_bytes=self.context.max_response_bytes, allowed_hosts=("data.epo.org",),
                allowed_path_prefixes=("/linked-data/doc/", "/linked-data/data/", "/linked-data/def/"),
            )
            status = response_status(SOURCE, operation, status_code)
            if status:
                return failed(SOURCE, operation, status, f"RH_EPO_LINKED_HTTP_{status_code}", f"Linked Open EP returned HTTP {status_code}", capability, meta, "EPO Linked Open EP official API reference (paths frozen from published reference)")
            try:
                data = parse_json_body(body, headers.get("content-type", "application/json"))
            except SourceFailure as exc:
                return failed(SOURCE, operation, exc.status, exc.code, exc.message, capability, meta, "EPO Linked Open EP official API reference (paths frozen from published reference)")
            if not isinstance(data, (dict, list)):
                return failed(SOURCE, operation, "error", "RH_EPO_LINKED_BODY", "Linked Open EP JSON root must be an object or array", capability, meta, "EPO Linked Open EP official API reference (paths frozen from published reference)")
            coverage = {"complete": not partial, "partial": partial}
            issues = ([{"code": "RH_EPO_LINKED_PAGE_PARTIAL", "message": "only the explicitly budgeted page was fetched; continue with next_page"}] if partial else [])
            if partial:
                coverage["next_page"] = query["_page"] + 1
            return result(SOURCE, operation, capability, "partial" if partial else "complete", data, coverage,
                          [{**meta, "spec_version": SPEC_REFERENCES}], issues)
        except SourceFailure as exc:
            return failed(SOURCE, operation, exc.status, exc.code, exc.message, capability, meta, str(SPEC_REFERENCES))

    def _request_parts(self, operation: str, params: dict[str, Any]) -> tuple[str, dict[str, Any], bool]:
        if operation == "application":
            _exact_keys(params, {"authority", "application_number"})
            authority = params["authority"]
            number = params["application_number"]
            if not isinstance(authority, str) or not re.fullmatch(r"[A-Z]{2,3}", authority) or not isinstance(number, str) or not re.fullmatch(r"[0-9]{1,20}", number):
                raise SourceFailure("error", "RH_EPO_LINKED_PARAMS", "application authority/number has an invalid form")
            return f"/doc/application/{quote(authority, safe='')}/{quote(number, safe='')}.json", {}, False
        if operation == "publication":
            _exact_keys(params, {"st3", "publication_number", "kind", "publication_date"})
            st3, number, kind, pub_date = (params[k] for k in ("st3", "publication_number", "kind", "publication_date"))
            if not isinstance(st3, str) or not re.fullmatch(r"[A-Z]{2,3}", st3) or not isinstance(number, str) or not re.fullmatch(r"[0-9]{1,20}", number) or not isinstance(kind, str) or not re.fullmatch(r"[A-Z0-9]{1,2}", kind) or not isinstance(pub_date, str) or not _valid_linked_date(pub_date):
                raise SourceFailure("error", "RH_EPO_LINKED_PARAMS", "publication identifier has an invalid form")
            return f"/data/publication/{quote(st3, safe='')}/{quote(number, safe='')}/{quote(kind, safe='')}/{quote(pub_date, safe='')}.json", {}, False
        if operation in {"classification_cpc", "classification_ipc"}:
            _exact_keys(params, {"symbol"})
            symbol = params["symbol"]
            if not isinstance(symbol, str) or not symbol.strip() or len(symbol) > 64 or any(char in symbol for char in "?#"):
                raise SourceFailure("error", "RH_EPO_LINKED_PARAMS", "classification symbol is invalid")
            namespace = "cpc" if operation.endswith("cpc") else "ipc"
            return f"/def/{namespace}/{quote(symbol, safe='')}.json", {}, False
        _exact_keys(params, {"from_date", "to_date", "page", "page_size"})
        low, high = params["from_date"], params["to_date"]
        if not isinstance(low, str) or not _valid_iso_date(low) or not isinstance(high, str) or not _valid_iso_date(high) or low > high:
            raise SourceFailure("error", "RH_EPO_LINKED_PARAMS", "from_date and to_date must be ordered ISO calendar dates")
        page, page_size = params["page"], params["page_size"]
        if isinstance(page, bool) or not isinstance(page, int) or page < 0 or isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 200:
            raise SourceFailure("error", "RH_EPO_LINKED_PARAMS", "page must be non-negative and page_size must be 1..200")
        query = {"min-publicationDate": low, "max-publicationDate": high, "_page": page, "_pageSize": page_size}
        # One physical request per operation keeps each page behind the core budget callback.
        # Callers can resume explicitly with the returned next_page; completion is never guessed.
        return "/data/publication/EP", query, True


def _exact_keys(params: dict[str, Any], required: set[str]) -> None:
    if set(params) != required:
        raise SourceFailure("error", "RH_EPO_LINKED_PARAMS", "parameter names do not match the documented operation")


def _valid_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _valid_linked_date(value: str) -> bool:
    return value == "-" or _valid_iso_date(value)
