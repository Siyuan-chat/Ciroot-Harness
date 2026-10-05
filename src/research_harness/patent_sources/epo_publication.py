"""EPO Publication Server v1.2 adapter for official publication artifacts."""
from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote, urljoin
from xml.etree import ElementTree

from .contracts import SourceContext, SourceFailure, failed, pending, request_once, response_status, result


BASE = "https://data.epo.org/publication-server/rest/v1.2"
SOURCE = "epo_eps"
SPEC_VERSION = "EPO European Publication Server REST v1.2, frozen PDF v1.6 (2024-04)"
PUBLICATION_ID = re.compile(r"EP[0-9]+NW[A-Z0-9]{1,2}")
FORMATS = {"xml", "html", "pdf", "zip"}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


class EPOPublicationAdapter:
    def __init__(self, context: SourceContext, *, enabled: bool):
        self.context, self.enabled = context, enabled

    def execute(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(operation, str) or not operation:
            return pending(SOURCE, "", "error", "RH_EPS_OPERATION", "operation must be a non-empty string")
        capabilities = {
            "publication_dates": "publication_date_index",
            "patents_for_date": "publication_date_list",
            "available_formats": "publication_format_lookup",
            "document": "official_publication_document",
        }
        if operation not in capabilities:
            return pending(SOURCE, operation, "pending_spec", "RH_EPS_OPERATION_UNVERIFIED", "operation is outside the frozen EPS v1.2 contract")
        capability = capabilities[operation]
        if self.enabled is not True:
            return pending(SOURCE, operation, "pending_activation", "RH_EPS_DISABLED", "EPS connector is not enabled", capability)
        if capability not in self.context.capabilities:
            return pending(SOURCE, operation, "unsupported", "RH_PATENT_CAPABILITY", "required capability was not granted", capability)
        if not isinstance(params, dict):
            return pending(SOURCE, operation, "error", "RH_EPS_PARAMS", "params must be an object", capability)
        meta = None
        try:
            path = self._path(operation, params)
            url = BASE + path
            status_code, headers, body, meta = request_once(
                self.context, source=SOURCE, operation=operation, capability=capability, method="GET", url=url,
                headers={"Accept": self._accept(operation, params)}, max_bytes=self.context.max_response_bytes,
                allowed_hosts=("data.epo.org",), allowed_path_prefixes=("/publication-server/rest/v1.2/",),
                accept=self._accept(operation, params),
            )
            status = response_status(SOURCE, operation, status_code)
            if status:
                return failed(SOURCE, operation, status, f"RH_EPS_HTTP_{status_code}", f"EPS returned HTTP {status_code}", capability, meta, SPEC_VERSION)
            content_type = headers.get("content-type", "").casefold()
            if not body:
                return failed(SOURCE, operation, "error", "RH_EPS_EMPTY_BODY", "EPS returned an empty response body", capability, meta, SPEC_VERSION)
            provenance = [{**meta, "spec_version": SPEC_VERSION}]
            if operation in {"publication_dates", "patents_for_date", "available_formats"}:
                parser = _Links()
                try:
                    html = body.decode("utf-8")
                    parser.feed(html)
                except (UnicodeDecodeError, ValueError):
                    return failed(SOURCE, operation, "error", "RH_EPS_INVALID_HTML", "EPS index response is not valid UTF-8 HTML", capability, meta, SPEC_VERSION)
                if "<html" not in html.casefold() or "</html>" not in html.casefold():
                    return failed(SOURCE, operation, "partial", "RH_EPS_UNRECOGNIZED_INDEX", "EPS response is not a recognizable HTML index", capability, meta, SPEC_VERSION)
                links = [urljoin(url, href) for href in parser.hrefs]
                if any(not _same_source_index_link(link) for link in links):
                    return failed(SOURCE, operation, "partial", "RH_EPS_EXTERNAL_INDEX_LINK", "EPS index contains a link outside the official publication server", capability, meta, SPEC_VERSION)
                if operation == "publication_dates":
                    values = sorted({m.group(1) for link in links if (m := re.search(r"/publication-dates/(\d{8})/patents(?:$|[?#])", link))})
                    data = {"publication_dates": values}
                elif operation == "patents_for_date":
                    values = sorted({m.group(1) for link in links if (m := re.search(r"/publication-dates/\d{8}/patents/(EP[0-9]+NW[A-Z0-9]{1,2})(?:$|[?#])", link))})
                    data = {"publication_ids": values}
                else:
                    values = sorted({m.group(1) for link in links if (m := re.search(r"/patents/EP[0-9]+NW[A-Z0-9]{1,2}/document\.(xml|html|pdf|zip)(?:$|[?#])", link))})
                    data = {"formats": values}
                if not data[next(iter(data))]:
                    return failed(SOURCE, operation, "partial", "RH_EPS_NO_MATCH_UNVERIFIED", "EPS HTML did not contain verifiable official index entries", capability, meta, SPEC_VERSION)
                return result(SOURCE, operation, capability, "complete", data, {"complete": True, "partial": False}, provenance)
            extension = params["format"].casefold()
            expected_type = {"xml": "application/xml", "html": "text/html", "pdf": "application/pdf", "zip": "application/zip"}[extension]
            if content_type.split(";", 1)[0].strip() != expected_type:
                return failed(SOURCE, operation, "error", "RH_EPS_CONTENT_TYPE", "EPS document content type does not match the requested format", capability, meta, SPEC_VERSION)
            if extension == "xml":
                try:
                    root = ElementTree.fromstring(body)
                    if root.tag.rsplit("}", 1)[-1] != "ep-patent-document" or root.attrib.get("id", "").upper() != params["publication_id"].upper():
                        return failed(SOURCE, operation, "partial", "RH_EPS_IDENTITY_MISMATCH", "EPS XML does not prove the requested publication identity", capability, meta, SPEC_VERSION)
                    parsed = {"root_tag": root.tag.rsplit("}", 1)[-1], "attributes": dict(root.attrib)}
                except ElementTree.ParseError:
                    return failed(SOURCE, operation, "error", "RH_EPS_INVALID_XML", "EPS XML document is not well formed", capability, meta, SPEC_VERSION)
            elif extension == "pdf":
                if not body.startswith(b"%PDF-"):
                    return failed(SOURCE, operation, "error", "RH_EPS_INVALID_PDF", "EPS response does not have a PDF signature", capability, meta, SPEC_VERSION)
                parsed = {"format": "pdf"}
            elif extension == "zip":
                if not body.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
                    return failed(SOURCE, operation, "error", "RH_EPS_INVALID_ZIP", "EPS response does not have a ZIP signature", capability, meta, SPEC_VERSION)
                parsed = {"format": "zip"}
            else:
                parsed = {"format": "html", "utf8_valid": _valid_utf8(body)}
                if not parsed["utf8_valid"]:
                    return failed(SOURCE, operation, "error", "RH_EPS_INVALID_HTML", "EPS HTML document is not valid UTF-8", capability, meta, SPEC_VERSION)
                html = body.decode("utf-8").casefold()
                if params["publication_id"].casefold() not in html or "<html" not in html or not any(word in html for word in ("claims", "description", "bibliographic", "patent")):
                    return failed(SOURCE, operation, "partial", "RH_EPS_HTML_IDENTITY_UNVERIFIED", "EPS HTML lacks a verifiable publication identity/content marker", capability, meta, SPEC_VERSION)
            data = {**parsed, "content_type": content_type, "content": body}
            return result(SOURCE, operation, capability, "complete", data, {"complete": True, "partial": False}, provenance)
        except SourceFailure as exc:
            return failed(SOURCE, operation, exc.status, exc.code, exc.message, capability, meta, SPEC_VERSION)

    @staticmethod
    def _path(operation: str, params: dict[str, Any]) -> str:
        if operation == "publication_dates":
            if params:
                raise SourceFailure("error", "RH_EPS_PARAMS", "publication_dates accepts no parameters")
            return "/publication-dates"
        if operation == "patents_for_date":
            value = params.get("publication_date")
            if set(params) != {"publication_date"} or not isinstance(value, str) or not _valid_date(value):
                raise SourceFailure("error", "RH_EPS_PARAMS", "publication_date must be a real YYYYMMDD date")
            return f"/publication-dates/{value}/patents"
        publication = params.get("publication_id")
        if not isinstance(publication, str) or not PUBLICATION_ID.fullmatch(publication):
            raise SourceFailure("error", "RH_EPS_PARAMS", "publication_id must match the EPS publication identifier form")
        publication = quote(publication, safe="")
        if operation == "available_formats":
            if set(params) != {"publication_id"}:
                raise SourceFailure("error", "RH_EPS_PARAMS", "available_formats accepts only publication_id")
            return f"/patents/{publication}"
        fmt = params.get("format")
        if operation == "document" and set(params) == {"publication_id", "format"} and isinstance(fmt, str) and fmt.casefold() in FORMATS:
            return f"/patents/{publication}/document.{fmt.casefold()}"
        raise SourceFailure("error", "RH_EPS_PARAMS", "unknown EPS parameter set or document format")

    @staticmethod
    def _accept(operation: str, params: dict[str, Any]) -> str:
        if operation in {"publication_dates", "patents_for_date", "available_formats"}:
            return "text/html"
        return {"xml": "application/xml", "html": "text/html", "pdf": "application/pdf", "zip": "application/zip"}[params["format"].casefold()]


def _valid_date(value: str) -> bool:
    if not re.fullmatch(r"\d{8}", value):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
        return True
    except ValueError:
        return False


def _valid_utf8(value: bytes) -> bool:
    try:
        value.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _same_source_index_link(value: str) -> bool:
    from urllib.parse import urlsplit
    parsed = urlsplit(value)
    return parsed.scheme == "https" and parsed.hostname == "data.epo.org" and parsed.port in (None, 443) and parsed.path.startswith("/publication-server/rest/v1.2/") and parsed.username is None and parsed.password is None
