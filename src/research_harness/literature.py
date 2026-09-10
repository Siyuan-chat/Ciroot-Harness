"""Bounded OpenAlex search and open-access PDF collection.

This module deliberately has no dependency on the investigation workflow or an
LLM.  It is usable by a person, another AI, or a later application adapter.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote, urljoin, urlsplit

import requests


OPENALEX_URL = "https://api.openalex.org/works"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/"
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_RETRIES = 2


class LiteratureError(Exception):
    """A safe, machine-readable error exposed by this module."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}


@dataclass
class _Budget:
    received: int = 0

    def add(self, count: int) -> None:
        self.received += count
        if self.received > MAX_TOTAL_BYTES:
            raise LiteratureError("byte_budget_exceeded", "the 300 MiB receive limit was reached")


def _read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiteratureError("invalid_input", "could not read JSON input") from exc


def _write_json(path: str | Path, value: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)


def _normalise_doi(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    doi = value.strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi.rstrip(" .;,") or None


def _abstract(index: Any) -> str | None:
    if not isinstance(index, dict):
        return None
    words: list[tuple[int, str]] = []
    for word, positions in index.items():
        if isinstance(word, str) and isinstance(positions, list):
            words.extend((position, word) for position in positions if isinstance(position, int))
    return " ".join(word for _, word in sorted(words)) or None


def _locations(work: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = work.get("locations")
    raw_locations = raw if isinstance(raw, list) else []
    best = work.get("best_oa_location")
    if isinstance(best, dict) and best not in raw_locations:
        raw_locations.append(best)
    locations: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for location in raw_locations:
        if not isinstance(location, dict):
            continue
        item = {
            "is_oa": bool(location.get("is_oa")),
            "pdf_url": location.get("pdf_url") if isinstance(location.get("pdf_url"), str) else None,
            "landing_page_url": location.get("landing_page_url") if isinstance(location.get("landing_page_url"), str) else None,
            "license": location.get("license") if isinstance(location.get("license"), str) else None,
            "version": location.get("version") if isinstance(location.get("version"), str) else None,
        }
        key = tuple(item.values())
        if key not in seen:
            seen.add(key)
            locations.append(item)
    return locations


def _record(work: Mapping[str, Any], query: str) -> dict[str, Any]:
    authors = []
    for authorship in work.get("authorships", []):
        author = authorship.get("author") if isinstance(authorship, dict) else None
        name = author.get("display_name") if isinstance(author, dict) else None
        if isinstance(name, str) and name:
            authors.append(name)
    return {
        "source_id": work.get("id") if isinstance(work.get("id"), str) else None,
        "title": work.get("title") if isinstance(work.get("title"), str) else "",
        "doi": _normalise_doi(work.get("doi")),
        "authors": authors,
        "year": work.get("publication_year") if isinstance(work.get("publication_year"), int) else None,
        "type": work.get("type") if isinstance(work.get("type"), str) else None,
        "abstract": _abstract(work.get("abstract_inverted_index")),
        "locations": _locations(work),
        "query_provenance": [query],
    }


def _require_search_config(config: Mapping[str, Any]) -> tuple[list[str], int, bool, int, int, bool, str]:
    queries = config.get("queries")
    if not isinstance(queries, list) or not queries or not all(isinstance(query, str) and query.strip() for query in queries):
        raise LiteratureError("invalid_input", "queries must be a non-empty list of strings")
    year_min = config.get("year_min")
    if not isinstance(year_min, int) or not 1900 <= year_min <= 2100:
        raise LiteratureError("invalid_input", "year_min must be a year")
    review_only = config.get("review_only", False)
    max_candidates = config.get("max_candidates")
    max_pages = config.get("max_pages_per_query")
    anonymous = config.get("anonymous", False)
    title_search = config.get("title_search", "")
    if not isinstance(review_only, bool) or not isinstance(anonymous, bool):
        raise LiteratureError("invalid_input", "review_only and anonymous must be booleans")
    if not isinstance(title_search, str):
        raise LiteratureError("invalid_input", "title_search must be a string")
    if not isinstance(max_candidates, int) or not 1 <= max_candidates <= 1000:
        raise LiteratureError("invalid_input", "max_candidates must be between 1 and 1000")
    if not isinstance(max_pages, int) or not 1 <= max_pages <= 20:
        raise LiteratureError("invalid_input", "max_pages_per_query must be between 1 and 20")
    return [query.strip() for query in queries], year_min, review_only, max_candidates, max_pages, anonymous, title_search.strip()


def _retry_after(response: Any) -> float:
    value = getattr(response, "headers", {}).get("Retry-After")
    try:
        return min(5.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.25


def _close(response: Any) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        close()


def search(config: Mapping[str, Any], *, session: Any = None) -> dict[str, Any]:
    """Search OpenAlex with bounded cursor pagination and save raw candidates."""
    queries, year_min, review_only, max_candidates, max_pages, anonymous, title_search = _require_search_config(config)
    api_key = None if anonymous else os.environ.get("OPENALEX_API_KEY")
    if not anonymous and not api_key:
        raise LiteratureError("missing_api_key", "set OPENALEX_API_KEY or use anonymous: true")
    client = session or requests.Session()
    headers = {"Accept": "application/json", "User-Agent": "research-harness-literature/0.1"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    records: list[dict[str, Any]] = []
    indexes: dict[str, int] = {}
    query_status: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for query in queries:
        if len(records) >= max_candidates:
            query_status.append({"query": query, "status": "not_run", "pages": 0, "next_cursor": None})
            continue
        cursor = "*"
        pages = 0
        state = "complete"
        while len(records) < max_candidates and pages < max_pages:
            filters = [f"from_publication_date:{year_min}-01-01"]
            if review_only:
                filters.append("type:review")
            if title_search:
                filters.append(f"title.search:{title_search}")
            params = {"search": query, "filter": ",".join(filters), "sort": "cited_by_count:desc", "cursor": cursor, "per-page": min(100, max_candidates - len(records))}
            response = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    response = client.get(OPENALEX_URL, params=params, headers=headers, timeout=(5, 30), allow_redirects=False)
                except requests.RequestException:
                    if attempt == MAX_RETRIES:
                        failures.append({"query": query, "code": "network_error"})
                        state = "failed"
                    else:
                        time.sleep(0.25)
                    continue
                status = getattr(response, "status_code", 0)
                if status in (401, 403):
                    _close(response)
                    failures.append({"query": query, "code": "authentication_failed"})
                    state = "failed"
                    break
                if status == 429 or 500 <= status < 600:
                    if attempt < MAX_RETRIES:
                        _close(response)
                        time.sleep(_retry_after(response))
                        continue
                    failures.append({"query": query, "code": "source_unavailable"})
                    _close(response)
                    state = "failed"
                    break
                if not 200 <= status < 300:
                    failures.append({"query": query, "code": "http_error"})
                    _close(response)
                    state = "failed"
                    break
                break
            if response is None or state == "failed":
                break
            try:
                payload = response.json()
                results = payload.get("results")
                meta = payload.get("meta")
                if not isinstance(results, list) or not isinstance(meta, dict):
                    raise ValueError
            except (ValueError, AttributeError, requests.JSONDecodeError):
                failures.append({"query": query, "code": "invalid_response"})
                state = "failed"
                _close(response)
                break
            _close(response)
            pages += 1
            for work in results:
                if not isinstance(work, dict):
                    continue
                candidate = _record(work, query)
                identity = candidate["doi"] or candidate["source_id"]
                if not identity:
                    identity = "title:" + candidate["title"].casefold() + ":" + str(candidate["year"])
                if identity in indexes:
                    previous = records[indexes[identity]]
                    if query not in previous["query_provenance"]:
                        previous["query_provenance"].append(query)
                    continue
                indexes[identity] = len(records)
                records.append(candidate)
                if len(records) == max_candidates:
                    state = "partial"
                    break
            next_cursor = meta.get("next_cursor")
            if not next_cursor:
                break
            if pages == max_pages:
                state = "partial"
                cursor = next_cursor
                break
            cursor = next_cursor
        query_status.append({"query": query, "status": state, "pages": pages, "next_cursor": None if cursor == "*" else cursor})
    states = [item["status"] for item in query_status]
    overall = "failed" if states and all(state == "failed" for state in states) else ("partial" if any(state in {"partial", "failed", "not_run"} for state in states) else "complete")
    return {
        "records": records,
        "search_status": {"status": overall, "anonymous": anonymous, "source": "openalex", "failures": failures},
        "queries": query_status,
    }


def _safe_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise LiteratureError("unsafe_url", "only public http(s) URLs without credentials are allowed")
    try:
        addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise LiteratureError("unsafe_url", "URL host could not be resolved") from exc
    for _, _, _, _, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global:
            raise LiteratureError("unsafe_url", "URL host resolves to a non-public address")
    return value


def _fetch_bytes(url: str, client: Any, budget: _Budget, maximum: int) -> tuple[bytes, Mapping[str, Any], str]:
    current = url
    for redirect in range(MAX_REDIRECTS + 1):
        _safe_url(current)
        response = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = client.get(current, headers={"User-Agent": "research-harness-literature/0.1"}, timeout=(5, 30), stream=True, allow_redirects=False)
            except requests.RequestException:
                if attempt == MAX_RETRIES:
                    raise LiteratureError("network_error", "request failed")
                time.sleep(0.25)
                continue
            status = getattr(response, "status_code", 0)
            if status in (401, 403):
                _close(response)
                raise LiteratureError("access_denied", "remote server denied access")
            if status == 429 or 500 <= status < 600:
                if attempt < MAX_RETRIES:
                    _close(response)
                    time.sleep(_retry_after(response))
                    continue
                _close(response)
                raise LiteratureError("source_unavailable", "remote server is temporarily unavailable")
            break
        if response is None:
            raise LiteratureError("network_error", "request failed")
        status = getattr(response, "status_code", 0)
        headers = getattr(response, "headers", {})
        if 300 <= status < 400:
            target = headers.get("Location")
            if not isinstance(target, str):
                _close(response)
                raise LiteratureError("invalid_redirect", "redirect has no target")
            if redirect == MAX_REDIRECTS:
                _close(response)
                raise LiteratureError("too_many_redirects", "redirect limit reached")
            current = urljoin(current, target)
            _close(response)
            continue
        if not 200 <= status < 300:
            _close(response)
            raise LiteratureError("http_error", "remote server returned an error")
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                budget.add(len(chunk))
                if size > maximum:
                    raise LiteratureError("file_too_large", "response exceeds its size limit")
                chunks.append(chunk)
        except (requests.RequestException, OSError) as exc:
            raise LiteratureError("network_error", "response stream failed") from exc
        finally:
            _close(response)
        return b"".join(chunks), headers, current
    raise LiteratureError("too_many_redirects", "redirect limit reached")


def _pdf_check(data: bytes, record: Mapping[str, Any]) -> tuple[int, bool, bool]:
    if not data.startswith(b"%PDF-"):
        raise LiteratureError("not_pdf", "response is not a PDF")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise LiteratureError("missing_pypdf", "install research-harness[literature] to validate PDFs") from exc
    try:
        from io import BytesIO
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise LiteratureError("encrypted_pdf", "PDF is encrypted")
        pages = len(reader.pages)
        if pages < 1:
            raise LiteratureError("invalid_pdf", "PDF has no pages")
        text = " ".join((page.extract_text() or "") for page in reader.pages[:2])
    except LiteratureError:
        raise
    except Exception as exc:
        raise LiteratureError("invalid_pdf", "PDF could not be parsed") from exc
    doi = _normalise_doi(record.get("doi"))
    title = record.get("title") if isinstance(record.get("title"), str) else ""
    compact = re.sub(r"\W+", "", text).casefold()
    doi_match = bool(doi and re.sub(r"\W+", "", doi).casefold() in compact)
    title_match = len(title) >= 12 and re.sub(r"\W+", "", title).casefold() in compact
    expected = record.get("expected_min_pages")
    too_short = isinstance(expected, int) and expected > 0 and pages < expected
    preview = bool(re.search(r"\bPDF\s+Page\s*\d+\s*(?:/|of)\s*\d+\b", text, flags=re.IGNORECASE))
    return pages, doi_match or title_match, too_short or preview


def _citation_pdf_url(page: bytes, base_url: str) -> str | None:
    document = page.decode("utf-8", errors="replace")
    tags = re.findall(r"<meta\b[^>]*>", document, flags=re.IGNORECASE)
    for tag in tags:
        name = re.search(r"\bname\s*=\s*['\"]citation_pdf_url['\"]", tag, flags=re.IGNORECASE)
        content = re.search(r"\bcontent\s*=\s*['\"]([^'\"]+)['\"]", tag, flags=re.IGNORECASE)
        if name and content:
            return urljoin(base_url, html.unescape(content.group(1)))
    return None


def _record_identity(record: Mapping[str, Any]) -> str:
    return str(_normalise_doi(record.get("doi")) or record.get("source_id") or (record.get("title"), record.get("year")))


def _filename(record: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(_record_identity(record).encode("utf-8")).hexdigest()[:12]
    title = re.sub(r"[^a-zA-Z0-9]+", "-", str(record.get("title") or "article")).strip("-")[:48] or "article"
    return f"{digest}_{title}.pdf"


def _locations_from_unpaywall(record: Mapping[str, Any], client: Any, budget: _Budget, email: str) -> list[dict[str, Any]]:
    doi = _normalise_doi(record.get("doi"))
    if not doi:
        return []
    try:
        data, _, _ = _fetch_bytes(f"{UNPAYWALL_URL}{quote(doi, safe='')}?email={quote(email)}", client, budget, MAX_HTML_BYTES)
        payload = json.loads(data)
    except (LiteratureError, json.JSONDecodeError):
        return []
    locations = payload.get("oa_locations") if isinstance(payload, dict) else None
    if not isinstance(locations, list):
        return []
    return [
        {"is_oa": True, "pdf_url": item.get("url_for_pdf"), "landing_page_url": item.get("url"), "license": item.get("license"), "version": item.get("version")}
        for item in locations if isinstance(item, dict)
    ]


def _log(handle: Any, **entry: Any) -> None:
    entry.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    handle.flush()


def _validate_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise LiteratureError("invalid_input", "each record must be an object")
    required = ("title", "doi", "year", "authors", "type", "locations")
    if any(key not in record for key in required) or not isinstance(record["title"], str) or not isinstance(record["authors"], list) or not isinstance(record["locations"], list):
        raise LiteratureError("invalid_input", "records need title, doi, year, authors, type and locations")
    if "expected_min_pages" in record and (not isinstance(record["expected_min_pages"], int) or record["expected_min_pages"] < 1):
        raise LiteratureError("invalid_input", "expected_min_pages must be a positive integer")
    return record


def _existing_success(catalog: Mapping[str, Any], identity: str) -> Mapping[str, Any] | None:
    for item in catalog.get("records", []) if isinstance(catalog.get("records"), list) else []:
        record = item.get("record") if isinstance(item, dict) else None
        outcome = item.get("download") if isinstance(item, dict) else None
        if isinstance(record, dict) and isinstance(outcome, dict) and _record_identity(record) == identity and outcome.get("status") == "success":
            return outcome
    return None


def _download_record(record: Mapping[str, Any], client: Any, budget: _Budget, pdf_dir: Path, known_hashes: set[str], use_unpaywall: bool, unpaywall_email: str | None, log_handle: Any) -> dict[str, Any]:
    locations = [item for item in record["locations"] if isinstance(item, dict) and item.get("is_oa")]
    if use_unpaywall and unpaywall_email:
        locations.extend(_locations_from_unpaywall(record, client, budget, unpaywall_email))

    def try_pdf(url: str, location: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            data, _, final_url = _fetch_bytes(url, client, budget, MAX_FILE_BYTES)
            pages, identity_match, preview = _pdf_check(data, record)
            if not identity_match:
                _log(log_handle, event="download", record_id=_record_identity(record), url=final_url, status="review", error="identity_mismatch", pages=pages)
                return None
            if preview:
                _log(log_handle, event="download", record_id=_record_identity(record), url=final_url, status="review", error="incomplete_pdf", pages=pages)
                return None
            digest = hashlib.sha256(data).hexdigest()
            if digest in known_hashes:
                outcome = {"status": "duplicate", "sha256": digest, "pages": pages, "url": final_url}
                _log(log_handle, event="download", record_id=_record_identity(record), **outcome)
                return outcome
            target = pdf_dir / _filename(record)
            if not (target.resolve().is_relative_to(pdf_dir.parent.resolve())):
                raise LiteratureError("unsafe_path", "download path escapes output directory")
            temporary = target.with_suffix(".pdf.part")
            temporary.write_bytes(data)
            temporary.replace(target)
            known_hashes.add(digest)
            outcome = {"status": "success", "path": str(target.relative_to(pdf_dir.parent)), "sha256": digest, "pages": pages, "url": final_url, "license": location.get("license"), "version": location.get("version")}
            _log(log_handle, event="download", record_id=_record_identity(record), **outcome)
            return outcome
        except LiteratureError as exc:
            if exc.code == "byte_budget_exceeded":
                raise
            _log(log_handle, event="download", record_id=_record_identity(record), url=url, status="failed", error=exc.code)
            return None

    for location in locations:
        if isinstance(location.get("pdf_url"), str):
            outcome = try_pdf(location["pdf_url"], location)
            if outcome:
                return outcome
        landing = location.get("landing_page_url")
        if isinstance(landing, str):
            try:
                page, _, final_url = _fetch_bytes(landing, client, budget, MAX_HTML_BYTES)
                discovered = _citation_pdf_url(page, final_url)
                if discovered:
                    outcome = try_pdf(discovered, location)
                    if outcome:
                        return outcome
            except LiteratureError as exc:
                if exc.code == "byte_budget_exceeded":
                    raise
                _log(log_handle, event="landing", record_id=_record_identity(record), status="failed", error=exc.code)
    return {"status": "review" if locations else "failed", "error": "no_verified_open_pdf"}


def _write_catalog_outputs(output: Path, catalog: Mapping[str, Any]) -> None:
    _write_json(output / "catalog.json", catalog)
    with (output / "catalog.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["title", "doi", "year", "type", "status", "pages", "path", "license", "version"])
        writer.writeheader()
        for item in catalog["records"]:
            record, result = item["record"], item["download"]
            def cell(value: Any) -> Any:
                if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
                    return "'" + value
                return value
            writer.writerow({"title": cell(record.get("title")), "doi": cell(record.get("doi")), "year": cell(record.get("year")), "type": cell(record.get("type")), "status": cell(result.get("status")), "pages": cell(result.get("pages")), "path": cell(result.get("path")), "license": cell(result.get("license")), "version": cell(result.get("version"))})
    with (output / "references.bib").open("w", encoding="utf-8") as handle:
        for index, item in enumerate(catalog["records"], start=1):
            record = item["record"]
            key = f"oa{index}"
            fields = {"title": record.get("title"), "author": " and ".join(record.get("authors", [])), "year": record.get("year"), "doi": record.get("doi")}
            handle.write(f"@article{{{key},\n")
            for name, value in fields.items():
                if value:
                    handle.write(f"  {name} = {{{str(value).replace('{', '').replace('}', '')}}},\n")
            handle.write("}\n\n")
    summary = f"# Open-access PDF collection\n\nOutcome: {catalog['outcome']}. Valid PDFs: {catalog['valid_pdf_count']} / requested {catalog['limit']}.\n\nPDF files are not a redistribution grant; retain each recorded licence and source URL.\n"
    (output / "README.md").write_text(summary, encoding="utf-8")


def download(manifest: Mapping[str, Any] | list[Any], output: str | Path, *, limit: int = 25, use_unpaywall: bool = False, session: Any = None) -> dict[str, Any]:
    """Download up to ``limit`` identity-checked open PDFs, preserving partial work."""
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise LiteratureError("invalid_input", "limit must be between 1 and 100")
    records = manifest.get("records") if isinstance(manifest, dict) else manifest
    if not isinstance(records, list):
        raise LiteratureError("invalid_input", "manifest must contain records")
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in records:
        record = _validate_record(raw)
        identity = _record_identity(record)
        if identity not in seen:
            seen.add(identity)
            unique.append(record)
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    pdf_dir = destination / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    prior_path = destination / "catalog.json"
    prior = _read_json(prior_path) if prior_path.exists() else {"records": []}
    client = session or requests.Session()
    budget = _Budget()
    known_hashes: set[str] = set()
    unpaywall_email = os.environ.get("UNPAYWALL_EMAIL") if use_unpaywall else None
    outcomes: list[dict[str, Any]] = []
    successes = 0
    with (destination / "download_log.jsonl").open("a", encoding="utf-8") as log_handle:
        for record in unique:
            if successes >= limit:
                break
            existing = _existing_success(prior, _record_identity(record))
            if existing:
                candidate = (destination / str(existing.get("path", ""))).resolve()
                try:
                    if not candidate.is_relative_to(destination.resolve()):
                        raise OSError("catalog path escapes output directory")
                    data = candidate.read_bytes()
                    pages, matched, preview = _pdf_check(data, record)
                    if matched and not preview:
                        result = dict(existing)
                        result.update({"status": "success", "pages": pages, "sha256": hashlib.sha256(data).hexdigest(), "reused": True})
                        known_hashes.add(result["sha256"])
                        successes += 1
                        _log(log_handle, event="reuse", record_id=_record_identity(record), status="success", path=result.get("path"))
                        outcomes.append({"record": record, "download": result})
                        continue
                except (OSError, LiteratureError):
                    pass
            try:
                result = _download_record(record, client, budget, pdf_dir, known_hashes, use_unpaywall, unpaywall_email, log_handle)
            except LiteratureError as exc:
                result = {"status": "failed", "error": exc.code}
                _log(log_handle, event="download", record_id=_record_identity(record), status="failed", error=exc.code)
                outcomes.append({"record": record, "download": result})
                break
            if result["status"] == "success":
                successes += 1
            outcomes.append({"record": record, "download": result})
        if use_unpaywall and not unpaywall_email:
            _log(log_handle, event="unpaywall", status="skipped", error="missing_unpaywall_email")
    catalog = {"outcome": "completed" if successes >= limit else "partial", "limit": limit, "valid_pdf_count": successes, "received_bytes": budget.received, "records": outcomes}
    _write_catalog_outputs(destination, catalog)
    return catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m research_harness.literature")
    commands = parser.add_subparsers(dest="command", required=True)
    search_parser = commands.add_parser("search")
    search_parser.add_argument("--config", required=True)
    search_parser.add_argument("--output", required=True)
    download_parser = commands.add_parser("download")
    download_parser.add_argument("--manifest", required=True)
    download_parser.add_argument("--output", required=True)
    download_parser.add_argument("--limit", type=int, default=25)
    download_parser.add_argument("--use-unpaywall", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            result = search(_read_json(args.config))
            _write_json(args.output, result)
        else:
            result = download(_read_json(args.manifest), args.output, limit=args.limit, use_unpaywall=args.use_unpaywall)
        print(json.dumps(result if args.command == "search" else {key: result[key] for key in ("outcome", "valid_pdf_count", "limit", "received_bytes")}, ensure_ascii=False))
        if args.command == "search":
            return 0 if result["search_status"]["status"] == "complete" else 4
        return 4 if result.get("outcome") == "partial" else 0
    except LiteratureError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2 if exc.code in {"invalid_input", "missing_api_key", "missing_pypdf"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
