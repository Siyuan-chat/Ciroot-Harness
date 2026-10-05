from __future__ import annotations
import json
import time

from research_harness.patent_sources.contracts import SourceContext, SourceFailure, request_once
from research_harness.patent_sources.gpss import GPSSAdapter
from research_harness.patent_sources.kipris import KIPRISAdapter
from research_harness.patent_sources.tipo import TIPOAdapter

IDENTITY = {"run_id": "synthetic-run", "task_id": "synthetic-task", "task_version": 1}

class Harness:
    def __init__(self, responses=None, *, deny_at=None):
        self.responses = list(responses or [])
        self.requests, self.reservations, self.deny_at = [], [], deny_at
    def reserve(self, **kwargs):
        self.reservations.append(kwargs)
        if self.deny_at == len(self.reservations):
            return None
        return f"synthetic-reservation-{len(self.reservations)}"
    def request(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected physical request")
        status, headers, body = self.responses.pop(0)
        return {"status_code": status, "headers": headers, "content": body,
                "url": request["url"], "redirect_chain": [], "request_identifier": "synthetic-http"}
    def context(self, capabilities=("case_lookup",), max_bytes=1024):
        return SourceContext(self.request, self.reserve, dict(IDENTITY), frozenset(capabilities), max_bytes)

def json_response(data, status=200):
    return status, {"content-type": "application/json"}, json.dumps(data).encode()

def token_decoder(_status, _headers, _body):
    return {"token": "synthetic-token", "expires_monotonic": time.monotonic() + 30}

def tipo(h, **kwargs):
    return TIPOAdapter(h.context(), enabled=True, username_env="TEST_TIPO_USER", password_env="TEST_TIPO_PASS",
                       token_decoder=token_decoder, token_decoder_source_id="synthetic:test-parser", **kwargs)

def with_credentials(monkeypatch):
    monkeypatch.setenv("TEST_TIPO_USER", "synthetic-user")
    monkeypatch.setenv("TEST_TIPO_PASS", "synthetic-password")

def auth_ok():
    return json_response({"token": "ignored by explicit synthetic decoder"})

def test_tipo_auth_budget_denial_and_no_auth_provenance(monkeypatch):
    with_credentials(monkeypatch)
    h = Harness([auth_ok()], deny_at=1)
    outcome = tipo(h).execute("case_info", {"case_id": "104142817"})
    assert outcome["status"] == "budget_denied"
    assert len(h.requests) == 0
    h = Harness([auth_ok(), json_response({"code": "0", "msg": "成功", "caseNo": "104142817", "title": "synthetic"})])
    outcome = tipo(h).execute("case_info", {"case_id": "104142817"})
    assert outcome["status"] == "complete"
    assert len(h.requests) == len(h.reservations) == 2
    assert h.requests[0]["url"].endswith("/getAuth")
    assert h.requests[0]["headers"]["Authorization"].startswith("Basic ")
    assert h.requests[0]["sensitive_headers"] == ["Authorization"]
    assert h.requests[1]["url"].endswith("/getCaseInfo/104142817")
    assert h.requests[1]["headers"]["Authorization"] == "Bearer synthetic-token"
    assert "synthetic-token" not in json.dumps(outcome)
    assert all("Basic " not in json.dumps(item) for item in outcome["provenance"])
    assert len(outcome["provenance"]) == 2
    assert [item["event"] for item in outcome["provenance"]] == ["authentication", "source_request"]
    assert outcome["provenance"][0]["token_decoder_source_id"] == "synthetic:test-parser"
    assert all("Authorization" not in json.dumps(item) for item in outcome["provenance"])

def test_tipo_auth_permission_and_wrong_token(monkeypatch):
    with_credentials(monkeypatch)
    for status, expected in ((401, "permission_required"), (403, "permission_required"), (429, "rate_limited")):
        h = Harness([(status, {"content-type": "application/json"}, b"secret body")])
        outcome = tipo(h).execute("case_info", {"case_id": "104142817"})
        assert outcome["status"] == expected
        assert "secret body" not in json.dumps(outcome)
        assert len(h.requests) == 1
    h = Harness([auth_ok(), (401, {"content-type": "application/json"}, b"denied")])
    outcome = tipo(h).execute("case_info", {"case_id": "104142817"})
    assert outcome["status"] == "permission_required"
    assert len(h.requests) == 2

def test_tipo_requires_official_decoder_and_credentials(monkeypatch):
    monkeypatch.delenv("TEST_TIPO_USER", raising=False)
    monkeypatch.delenv("TEST_TIPO_PASS", raising=False)
    h = Harness()
    adapter = TIPOAdapter(h.context(), enabled=True, username_env="TEST_TIPO_USER", password_env="TEST_TIPO_PASS")
    assert adapter.execute("case_info", {"case_id": "104142817"})["status"] == "pending_activation"
    with_credentials(monkeypatch)
    assert adapter.execute("case_info", {"case_id": "104142817"})["status"] == "pending_spec"
    assert adapter.diagnose()["status"] == "pending_spec"
    assert not h.requests

def test_tipo_identity_status_and_exact_relation_spelling(monkeypatch):
    with_credentials(monkeypatch)
    h = Harness([auth_ok(), json_response({"code": "0", "caseNo": "other"})])
    assert tipo(h).execute("case_info", {"case_id": "104142817"})["issues"][0]["code"] == "RH_TIPO_WRONG_IDENTITY"
    h = Harness([auth_ok(), json_response({"code": "1", "caseNo": "104142817"})])
    assert tipo(h).execute("case_info", {"case_id": "104142817"})["status"] == "partial"
    h = Harness([auth_ok(), json_response({"code": "0", "relationCase": []})])
    assert tipo(h).execute("related_cases", {"case_no": "104142817"})["status"] == "complete"
    assert h.requests[1]["url"].endswith("/getReationCase/104142817")
    assert "getRelationCase" not in h.requests[1]["url"]

def test_tipo_rejects_evil_file_url_before_auth_and_empty_or_wrong_file(monkeypatch):
    with_credentials(monkeypatch)
    h = Harness()
    for hostile_path in ("/S092_API/opd1/getfile/../getAuth", "/S092_API/opd1/getfile/%2e%2e/getAuth",
                         "/S092_API/opd1/getfile/%252e%252e/getAuth", "/S092_API/opd1/getfile/%2f..%2fgetAuth",
                         "/S092_API/opd1/getfile\\..\\getAuth"):
        outcome = tipo(h).execute("download_file", {"file_url": "https://tiponet.tipo.gov.tw" + hostile_path})
        assert outcome["status"] == "error"
    outcome = tipo(h).execute("download_file", {"file_url": "https://attacker.invalid/S092_API/opd1/getfile/x"})
    assert outcome["status"] == "error"
    assert not h.requests and not h.reservations
    h = Harness([auth_ok(), (200, {"content-type": "application/pdf"}, b"")])
    assert tipo(h).execute("download_file", {"file_url": "https://tiponet.tipo.gov.tw/S092_IN/opd1/getfile/id"})["issues"][0]["code"] == "RH_TIPO_EMPTY_FILE"
    h = Harness([auth_ok(), (200, {"content-type": "application/pdf"}, b"not pdf")])
    assert tipo(h).execute("download_file", {"file_url": "https://tiponet.tipo.gov.tw/S092_API/opd1/getfile/id"})["status"] == "partial"

def test_tipo_missing_body_and_wrong_case_response_are_partial(monkeypatch):
    with_credentials(monkeypatch)
    h = Harness([auth_ok(), json_response({"code": "0", "caseNo": "104142817"})])
    assert tipo(h).execute("result_file_list", {"case_no": "104142817"})["status"] == "partial"
    h = Harness([auth_ok(), json_response({"caseNo": "104142817"})])
    assert tipo(h).execute("related_cases", {"case_no": "104142817"})["status"] == "partial"

def test_kipris_is_zero_dispatch_pending_secure_transport_even_with_key(monkeypatch):
    monkeypatch.setenv("TEST_KIPRIS_KEY", "synthetic-key")
    h = Harness()
    adapter = KIPRISAdapter(h.context(("patent_search",)), enabled=True, api_key_env="TEST_KIPRIS_KEY")
    out = adapter.execute("advanced_search", {"inventionTitle": "membrane"})
    assert out["status"] == "pending_secure_transport"
    assert adapter.diagnose()["documented_http_contract"]["method"] == "GET"
    assert adapter.diagnose()["credential_configured"] is True
    assert not h.requests and not h.reservations

def test_kipris_pending_activation_and_unknown_operation():
    h = Harness()
    assert KIPRISAdapter(h.context(), enabled=False).execute("advanced_search")["status"] == "pending_activation"
    assert KIPRISAdapter(h.context(), enabled=True).execute("guess_route")["status"] == "pending_spec"
    assert not h.requests

def test_gpss_pending_spec_has_no_guessed_route_or_dispatch():
    h = Harness()
    adapter = GPSSAdapter(h.context(("patent_search",)), enabled=True)
    out = adapter.execute("query", {"query": "not dispatched"})
    assert out["status"] == "pending_spec"
    assert adapter.diagnose()["dispatch_enabled"] is False
    assert not h.requests and not h.reservations

def test_gpss_activation_and_unknown_operation():
    h = Harness()
    assert GPSSAdapter(h.context(), enabled=False).execute("query")["status"] == "pending_activation"
    assert GPSSAdapter(h.context(), enabled=True).execute("invented")["status"] == "pending_spec"
    assert not h.requests


def test_shared_request_rejects_same_origin_final_url_path_traversal():
    h = Harness([json_response({"ok": True})])
    # Same host is not enough: redirects must also remain inside a safe path.
    original_request = h.request
    def request_with_traversal(request):
        response = original_request(request)
        response["url"] = "https://tiponet.tipo.gov.tw/S092_API/opd1/getfile/../getAuth"
        response["redirect_chain"] = [response["url"]]
        return response
    context = SourceContext(request_with_traversal, h.reserve, dict(IDENTITY), frozenset({"case_lookup"}), 1024)
    try:
        request_once(context, source="tipo_opd", operation="getfile", capability="case_lookup",
                     method="GET", url="https://tiponet.tipo.gov.tw/S092_API/opd1/getfile/id",
                     allowed_hosts=("tiponet.tipo.gov.tw",),
                     allowed_path_prefixes=("/S092_API/opd1/", "/S092_IN/opd1/"))
    except SourceFailure as exc:
        assert exc.code == "RH_PATENT_REDIRECT"
    else:
        raise AssertionError("unsafe same-origin final URL was accepted")
