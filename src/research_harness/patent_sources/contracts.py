"""Shared callback, budget, response, and provenance contract for patent sources."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class SourceContext:
    request: Callable[[dict[str, Any]], Any]
    reserve_budget: Callable[..., Any]
    identity: dict[str, Any]
    capabilities: frozenset[str]
    max_response_bytes: int = 10 * 1024 * 1024

    def __post_init__(self):
        if not callable(self.request) or not callable(self.reserve_budget):
            raise ValueError("request and reserve_budget callbacks are required")
        if not isinstance(self.identity, dict) or not all(isinstance(self.identity.get(k), str) and self.identity[k] for k in ("run_id", "task_id")):
            raise ValueError("identity requires run_id and task_id")
        if isinstance(self.identity.get("task_version"), bool) or not isinstance(self.identity.get("task_version"), int) or self.identity["task_version"] < 1:
            raise ValueError("identity.task_version must be a positive integer")
        if isinstance(self.max_response_bytes, bool) or not isinstance(self.max_response_bytes, int) or self.max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        if not isinstance(self.capabilities, frozenset) or any(not isinstance(item, str) for item in self.capabilities):
            raise ValueError("capabilities must be a frozenset of strings")


class SourceFailure(Exception):
    def __init__(self, status: str, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def pending(source: str, operation: str, status: str, code: str, message: str, capability: str | None = None) -> dict[str, Any]:
    return {"source": source, "operation": operation, "status": status, "capability": capability,
            "data": None, "coverage": {"complete": False, "partial": status == "partial"}, "issues": [{"code": code, "message": message}], "provenance": []}


def require_capability(context: SourceContext, capability: str, source: str, operation: str) -> dict[str, Any] | None:
    if capability not in context.capabilities:
        return pending(source, operation, "unsupported", "RH_PATENT_CAPABILITY", "required source capability was not granted", capability)
    return None


def request_once(context: SourceContext, *, source: str, operation: str, capability: str, method: str, url: str,
                 headers: dict[str, str] | None = None, params: dict[str, Any] | None = None, body: bytes | None = None,
                 max_bytes: int | None = None, allowed_hosts: tuple[str, ...], allowed_path_prefixes: tuple[str, ...],
                 accept: str | None = None, sensitive_headers: tuple[str, ...] = ()) -> tuple[int, dict[str, str], bytes, dict[str, Any]]:
    """Reserve once, make exactly one injected physical request, and check its provenance boundary."""
    if not isinstance(capability, str) or not capability or capability not in context.capabilities:
        raise SourceFailure("unsupported", "RH_PATENT_CAPABILITY", "required source capability was not granted")
    if method not in {"GET", "POST"} or not _allowed_url(url, allowed_hosts, allowed_path_prefixes):
        raise SourceFailure("error", "RH_PATENT_URL", "initial request URL or method is outside the source allowlist")
    if max_bytes is not None and (isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1):
        raise SourceFailure("error", "RH_PATENT_SIZE_LIMIT", "max_bytes must be a positive integer")
    limit = min(max_bytes or context.max_response_bytes, context.max_response_bytes)
    try:
        reservation = context.reserve_budget(operation=operation, source=source, identity=dict(context.identity),
                                             capability=capability, max_response_bytes=limit)
    except Exception as exc:
        raise SourceFailure("budget_denied", "RH_PATENT_BUDGET", "core budget callback denied the request") from exc
    if not ((isinstance(reservation, str) and reservation.strip()) or
            (isinstance(reservation, dict) and bool(reservation))):
        raise SourceFailure("budget_denied", "RH_PATENT_BUDGET", "core budget callback denied the request")
    request = {"method": method, "url": url, "headers": dict(headers or {}), "params": dict(params or {}),
               "body": body, "operation": operation, "source": source, "identity": dict(context.identity),
               "capability": capability, "budget_reservation": reservation, "max_response_bytes": limit,
               "allow_redirects": False, "allowed_redirect_hosts": list(allowed_hosts),
               "allowed_redirect_path_prefixes": list(allowed_path_prefixes), "sensitive_headers": list(sensitive_headers), "accept": accept}
    try:
        response = context.request(request)
    except Exception as exc:
        raise SourceFailure("error", "RH_PATENT_TRANSPORT", "injected request callback failed") from exc
    if not isinstance(response, dict):
        raise SourceFailure("error", "RH_PATENT_TRANSPORT", "injected request callback must return a response object")
    try:
        status = int(response.get("status_code", response.get("status")))
    except (TypeError, ValueError) as exc:
        raise SourceFailure("error", "RH_PATENT_TRANSPORT", "response status_code is missing") from exc
    raw_headers = response.get("headers") or {}
    if not isinstance(raw_headers, dict):
        raise SourceFailure("error", "RH_PATENT_TRANSPORT", "response headers must be an object")
    headers_out = {str(k).casefold(): str(v) for k, v in raw_headers.items()}
    content = response.get("content")
    if not isinstance(content, bytes):
        raise SourceFailure("error", "RH_PATENT_RESPONSE_BODY", "response content must be bytes")
    if len(content) > limit:
        raise SourceFailure("error", "RH_PATENT_SIZE_LIMIT", "response exceeded the reserved byte limit")
    final_url = response.get("url", url)
    chain = response.get("redirect_chain", [])
    if not isinstance(chain, list) or not isinstance(final_url, str):
        raise SourceFailure("error", "RH_PATENT_REDIRECT", "redirect metadata is invalid")
    for target in [*chain, final_url]:
        if not isinstance(target, str) or not _allowed_url(target, allowed_hosts, allowed_path_prefixes):
            raise SourceFailure("error", "RH_PATENT_REDIRECT", "response redirect escaped the source allowlist")
    meta = {"request_url": url, "final_url": final_url, "redirect_chain": chain, "response_bytes": len(content),
            "content_type": headers_out.get("content-type", "application/octet-stream"),
            "content_sha256": hashlib.sha256(content).hexdigest(), "status_code": status,
            "request_identifier": response.get("request_identifier")}
    return status, headers_out, content, meta


def _allowed_url(url: str, hosts: tuple[str, ...], prefixes: tuple[str, ...]) -> bool:
    try:
        parsed = urlsplit(url)
        path = parsed.path
        if "\\" in path:
            return False
        decoded = path
        for _ in range(5):
            next_path = unquote(decoded)
            if "\\" in next_path:
                return False
            if any(part in {".", ".."} for part in next_path.split("/")):
                return False
            if next_path == decoded:
                break
            decoded = next_path
        return (parsed.scheme == "https" and parsed.hostname in hosts and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None and any(path.startswith(prefix) for prefix in prefixes))
    except ValueError:
        return False


def response_status(source: str, operation: str, status: int) -> str | None:
    if status == 404:
        return "no_match"
    if status in (401, 403):
        return "permission_required"
    if status == 429:
        return "rate_limited"
    if status == 413:
        return "partial"
    if status < 200 or status >= 300:
        return "error"
    return None


def parse_json_body(body: bytes, content_type: str) -> Any:
    if "json" not in content_type.casefold() and not body.lstrip().startswith((b"{", b"[")):
        raise SourceFailure("error", "RH_PATENT_CONTENT_TYPE", "expected a JSON response")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFailure("error", "RH_PATENT_INVALID_BODY", "response body is not valid UTF-8 JSON") from exc


def result(source: str, operation: str, capability: str, status: str, data: Any, coverage: dict[str, Any], provenance: list[dict[str, Any]], issues: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"source": source, "operation": operation, "status": status, "capability": capability, "data": data,
            "coverage": coverage, "issues": issues or [], "provenance": provenance}


def add_provenance(outcome: dict[str, Any], meta: dict[str, Any], spec_version: str) -> dict[str, Any]:
    outcome["provenance"] = [{**meta, "spec_version": spec_version}]
    return outcome


def failed(source: str, operation: str, status: str, code: str, message: str, capability: str | None = None,
           meta: dict[str, Any] | None = None, spec_version: str | None = None) -> dict[str, Any]:
    outcome = pending(source, operation, status, code, message, capability)
    if meta is not None and spec_version is not None:
        add_provenance(outcome, meta, spec_version)
    return outcome
