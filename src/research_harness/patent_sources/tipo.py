"""Taiwan TIPO OPD adapter; auth response parsing is deliberately opt-in."""
from __future__ import annotations
import base64
import os
import math
import time
from typing import Any, Callable
from urllib.parse import urlsplit
from .contracts import SourceContext, SourceFailure, failed, parse_json_body, pending, request_once, response_status, result

SOURCE = "tipo_opd"
BASE = "https://tiponet.tipo.gov.tw/S092_API/opd1"
AUTH_URL = BASE + "/getAuth"
SPEC_URL = "https://www.tipo.gov.tw/wSite/public/Attachment/0/f1745825024395.pdf"
SPEC_VERSION = "TIPO OPD API guide, frozen 2026-10-05"
CAPABILITY = "case_lookup"
OPERATIONS = {"case_info", "related_cases", "result_file_list", "download_file"}
HOST = "tiponet.tipo.gov.tw"
API_PREFIXES = ("/S092_API/opd1/", "/S092_IN/opd1/")

class TIPOAdapter:
    """Each execute operation obtains a fresh token and discards it on return.

    token_decoder is an explicit integration seam: it must return {token,
    expires_monotonic}, with an official source_id supplied by the caller. No
    default parser is provided because the frozen guide does not define the auth
    response or expiry schema. The token never survives a single execute call.
    """
    def __init__(self, context: SourceContext, *, enabled: bool = False,
                 username_env: str = "TIPO_API_USERNAME", password_env: str = "TIPO_API_PASSWORD",
                 token_decoder: Callable[[int, dict[str, str], bytes], dict[str, Any]] | None = None,
                 token_decoder_source_id: str | None = None):
        self.context, self.enabled = context, enabled
        self.username_env, self.password_env = username_env, password_env
        self.token_decoder, self.token_decoder_source_id = token_decoder, token_decoder_source_id

    def diagnose(self) -> dict[str, Any]:
        credentials = bool(os.environ.get(self.username_env) and os.environ.get(self.password_env))
        parser_ready = callable(self.token_decoder) and bool(self.token_decoder_source_id)
        status = "pending_activation" if not self.enabled or not credentials else ("pending_spec" if not parser_ready else "ready_for_core_activation")
        return {"source": SOURCE, "status": status, "capability": CAPABILITY,
                "capability_granted": CAPABILITY in self.context.capabilities, "credentials_configured": credentials,
                "token_decoder_configured": parser_ready, "official_reference": SPEC_URL,
                "spec_version": SPEC_VERSION, "dispatch_enabled": False,
                "blocking_reason": "TIPO guide does not define getAuth response or token expiry; provide a decoder backed by an identified official source" if not parser_ready else None,
                "token_lifetime": "one execute operation only; discarded before return"}

    def execute(self, operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = params or {}
        if operation not in OPERATIONS:
            return pending(SOURCE, str(operation), "pending_spec", "RH_TIPO_OPERATION", "operation is not in the frozen TIPO OPD contract", CAPABILITY)
        if not self.enabled:
            return pending(SOURCE, operation, "pending_activation", "RH_TIPO_DISABLED", "TIPO connector is disabled", CAPABILITY)
        if CAPABILITY not in self.context.capabilities:
            return pending(SOURCE, operation, "unsupported", "RH_PATENT_CAPABILITY", "case lookup capability was not granted", CAPABILITY)
        username, password = os.environ.get(self.username_env), os.environ.get(self.password_env)
        if not username or not password:
            return pending(SOURCE, operation, "pending_activation", "RH_TIPO_CREDENTIALS_MISSING", "TIPO username/password environment variables are not set", CAPABILITY)
        if not callable(self.token_decoder) or not self.token_decoder_source_id:
            return pending(SOURCE, operation, "pending_spec", "RH_TIPO_AUTH_SCHEMA_MISSING", "official getAuth response and expiry schema are not confirmed; no request is sent", CAPABILITY)
        try:
            self._validate_params(operation, params)
            # Reject hostile or malformed file URLs before spending auth budget.
            url, op_name = self._operation_url(operation, params)
        except SourceFailure as exc:
            return pending(SOURCE, operation, exc.status, exc.code, exc.message, CAPABILITY)
        try:
            basic = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            status, headers, body, auth_meta = request_once(self.context, source=SOURCE, operation="getAuth", capability=CAPABILITY, method="GET", url=AUTH_URL,
                headers={"Authorization": f"Basic {basic}"}, allowed_hosts=(HOST,), allowed_path_prefixes=API_PREFIXES, accept="application/json", sensitive_headers=("Authorization",))
            auth_event = {**auth_meta, "event": "authentication", "spec_version": SPEC_VERSION,
                          "token_decoder_source_id": self.token_decoder_source_id}
            auth_state = response_status(SOURCE, operation, status)
            if auth_state:
                return failed(SOURCE, operation, auth_state, f"RH_TIPO_AUTH_HTTP_{status}", "TIPO authentication request failed", CAPABILITY, {"status_code": status, "request_url": auth_meta["request_url"], "content_sha256": auth_meta["content_sha256"]}, SPEC_VERSION)
            try:
                decoded = self.token_decoder(status, headers, body)
            except Exception:
                return self._trace(pending(SOURCE, operation, "pending_spec", "RH_TIPO_TOKEN_DECODE_FAILED", "configured token decoder rejected getAuth response", CAPABILITY), auth_event)
            if not isinstance(decoded, dict) or not isinstance(decoded.get("token"), str) or not decoded["token"]:
                return self._trace(pending(SOURCE, operation, "pending_spec", "RH_TIPO_TOKEN_INVALID", "token decoder did not return a token", CAPABILITY), auth_event)
            expiry = decoded.get("expires_monotonic")
            if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= time.monotonic():
                return self._trace(pending(SOURCE, operation, "pending_spec", "RH_TIPO_TOKEN_EXPIRY_INVALID", "token decoder must return a future official expiry as monotonic seconds", CAPABILITY), auth_event)
            token = decoded["token"]
            status, headers, body, req_meta = request_once(self.context, source=SOURCE, operation=op_name, capability=CAPABILITY, method="GET", url=url,
                headers={"Authorization": f"Bearer {token}"}, allowed_hosts=(HOST,), allowed_path_prefixes=API_PREFIXES, accept="application/json, application/pdf, application/zip", sensitive_headers=("Authorization",))
            state = response_status(SOURCE, operation, status)
            if state:
                outcome = failed(SOURCE, operation, state, f"RH_TIPO_HTTP_{status}", "TIPO source request failed", CAPABILITY, {"status_code": status, "request_url": req_meta["request_url"], "content_sha256": req_meta["content_sha256"]}, SPEC_VERSION)
                return self._trace(outcome, auth_event, {**req_meta, "event": "source_request", "spec_version": SPEC_VERSION})
            if operation == "download_file":
                return self._trace(self._file_result(operation, body, headers, req_meta), auth_event, {**req_meta, "event": "source_request", "spec_version": SPEC_VERSION})
            data = parse_json_body(body, headers.get("content-type", ""))
            if not isinstance(data, dict):
                return self._trace(pending(SOURCE, operation, "partial", "RH_TIPO_INVALID_RESPONSE", "TIPO response must be a JSON object", CAPABILITY), auth_event, {**req_meta, "event": "source_request", "spec_version": SPEC_VERSION})
            if operation == "case_info":
                returned = next((data.get(k) for k in ("caseNo", "publishNo", "announcementNo") if isinstance(data.get(k), str) and data[k]), None)
                if returned and returned != params["case_id"]:
                    return self._trace(pending(SOURCE, operation, "partial", "RH_TIPO_WRONG_IDENTITY", "returned case identifier does not match the requested identifier", CAPABILITY), auth_event, {**req_meta, "event": "source_request", "spec_version": SPEC_VERSION})
                if not returned:
                    return self._trace(pending(SOURCE, operation, "partial", "RH_TIPO_IDENTITY_INSUFFICIENT", "response has no recognized case identity", CAPABILITY), auth_event, {**req_meta, "event": "source_request", "spec_version": SPEC_VERSION})
                if data.get("code") != "0":
                    return self._trace(pending(SOURCE, operation, "partial", "RH_TIPO_RESULT_STATUS", "TIPO response code is not the documented success code 0", CAPABILITY), auth_event, {**req_meta, "event": "source_request", "spec_version": SPEC_VERSION})
            elif operation == "related_cases" and (data.get("code") != "0" or not isinstance(data.get("relationCase"), list)):
                return self._trace(pending(SOURCE, operation, "partial", "RH_TIPO_RELATION_SHAPE", "relation response lacks the documented relationCase field", CAPABILITY), auth_event, {**req_meta, "event": "source_request", "spec_version": SPEC_VERSION})
            elif operation == "result_file_list" and (data.get("code") != "0" or not isinstance(data.get("resultFileList"), list)):
                return self._trace(pending(SOURCE, operation, "partial", "RH_TIPO_FILELIST_SHAPE", "response lacks the documented resultFileList field", CAPABILITY), auth_event, {**req_meta, "event": "source_request", "spec_version": SPEC_VERSION})
            source_event = {**req_meta, "event": "source_request", "spec_version": SPEC_VERSION}
            outcome = result(SOURCE, operation, CAPABILITY, "complete", data, {"complete": True, "partial": False}, [auth_event, source_event])
            return outcome
        except SourceFailure as exc:
            outcome = failed(SOURCE, operation, exc.status, exc.code, exc.message, CAPABILITY, None, SPEC_VERSION)
            if 'auth_event' in locals():
                return self._trace(outcome, auth_event, ({**req_meta, "event": "source_request", "spec_version": SPEC_VERSION} if 'req_meta' in locals() else None))
            return outcome
        finally:
            token = None
            basic = None

    @staticmethod
    def _validate_params(operation: str, params: dict[str, Any]) -> None:
        expected = {"case_info": "case_id", "related_cases": "case_no", "result_file_list": "case_no", "download_file": "file_url"}[operation]
        if set(params) != {expected} or not isinstance(params.get(expected), str) or not params[expected].strip():
            raise SourceFailure("error", "RH_TIPO_PARAMS", f"{operation} expects exactly {expected}")
        if operation != "download_file" and any(c in params[expected] for c in "?#/\\"):
            raise SourceFailure("error", "RH_TIPO_PARAMS", "case identifier contains unsafe path/query characters")

    @staticmethod
    def _operation_url(operation: str, params: dict[str, Any]) -> tuple[str, str]:
        from urllib.parse import quote
        if operation == "case_info":
            return BASE + "/getCaseInfo/" + quote(params["case_id"], safe=""), "getCaseInfo"
        if operation == "related_cases":
            return BASE + "/getReationCase/" + quote(params["case_no"], safe=""), "getReationCase"
        if operation == "result_file_list":
            return BASE + "/getResultFileList/" + quote(params["case_no"], safe=""), "getResultFileList"
        target = urlsplit(params["file_url"])
        from .contracts import _allowed_url
        if ("%2f" in target.path.casefold() or "%5c" in target.path.casefold()
                or not _allowed_url(params["file_url"], (HOST,), API_PREFIXES) or target.scheme != "https"
                or target.hostname != HOST or target.port not in (None, 443) or target.username
                or target.password or target.query or target.fragment or not target.path.startswith(API_PREFIXES)):
            raise SourceFailure("error", "RH_TIPO_FILE_URL", "file URL is outside the official TIPO getfile allowlist")
        if "/getfile/" not in target.path:
            raise SourceFailure("error", "RH_TIPO_FILE_URL", "file URL is not a documented getfile route")
        return params["file_url"], "getfile"

    @staticmethod
    def _trace(outcome: dict[str, Any], auth_event: dict[str, Any], source_event: dict[str, Any] | None = None) -> dict[str, Any]:
        events = [auth_event]
        if source_event is not None:
            events.append(source_event)
        outcome["provenance"] = events
        return outcome

    def _file_result(self, operation: str, body: bytes, headers: dict[str, str], meta: dict[str, Any]) -> dict[str, Any]:
        ctype = headers.get("content-type", "").casefold()
        if not body:
            return pending(SOURCE, operation, "partial", "RH_TIPO_EMPTY_FILE", "TIPO returned an empty file body", CAPABILITY)
        if not (body.startswith(b"%PDF-") or body.startswith(b"PK\x03\x04")):
            return pending(SOURCE, operation, "partial", "RH_TIPO_FILE_MAGIC", "download is not a recognized PDF or ZIP body", CAPABILITY)
        if "pdf" in ctype and not body.startswith(b"%PDF-") or "zip" in ctype and not body.startswith(b"PK\x03\x04"):
            return pending(SOURCE, operation, "partial", "RH_TIPO_FILE_TYPE", "file content type conflicts with file signature", CAPABILITY)
        return result(SOURCE, operation, CAPABILITY, "complete", {"bytes": body, "content_type": ctype}, {"complete": True, "partial": False}, [{**meta, "spec_version": SPEC_VERSION}])
