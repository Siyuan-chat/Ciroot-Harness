"""Offline contract tests: every patent request is a synthetic injected callback."""
import hashlib
import pytest

from research_harness.patent_sources.contracts import SourceContext
from research_harness.patent_sources.epo_linked import EPOLinkedAdapter
from research_harness.patent_sources.epo_publication import EPOPublicationAdapter
from research_harness.patent_sources.jpo import JPOAdapter, OPERATIONS


IDENTITY = {"run_id": "run-synthetic", "task_id": "task-synthetic", "task_version": 2}


class OfflineHarness:
    def __init__(self, content=b'{"result":{"statusCode":"100","data":{}}}', status=200, headers=None, *, final_url=None, redirect_chain=None, deny=False, reservation=None):
        self.content, self.status = content, status
        self.headers = headers or {"content-type": "application/json"}
        self.final_url, self.redirect_chain, self.deny, self.reservation = final_url, redirect_chain or [], deny, reservation
        self.requests, self.reservations = [], []

    def reserve(self, **kwargs):
        self.reservations.append(kwargs)
        return False if self.deny else (self.reservation if self.reservation is not None else f"synthetic-reservation-{len(self.reservations)}")

    def request(self, request):
        self.requests.append(request)
        return {"status_code": self.status, "headers": self.headers, "content": self.content,
                **({"url": self.final_url} if self.final_url else {}),
                "redirect_chain": self.redirect_chain, "request_identifier": "synthetic-request"}

    def context(self, capabilities, *, max_response_bytes=1024):
        return SourceContext(self.request, self.reserve, dict(IDENTITY), frozenset(capabilities), max_response_bytes)


def _jpo_params(operation):
    if operation in {"app_progress", "app_progress_simple", "divisional_app_info", "priority_right_app_info", "application_documents", "dispatch_documents", "refusal_reason_documents", "cite_doc_info", "registration_info", "jpp_fixed_address"}:
        return {"application_number": "2020008423"}
    if operation == "applicant_attorney_by_code":
        return {"applicant_code": "718000266"}
    if operation == "applicant_attorney_by_name":
        return {"applicant_name": "特許庁長官"}
    if operation == "case_number_reference":
        return {"case_type": "application", "case_number": "2020008423"}
    if operation == "pct_national_phase_application_number":
        return {"case_type": "international_application", "case_number": "JP2019011858"}
    if operation in {"opd_family", "opd_family_list"}:
        return {"case_type": "application", "case_reference": "JP.2015500001.A"}
    if operation in {"opd_global_doc_list", "opd_global_cite_class"}:
        return {"case_reference": "JP.2015500001.A"}
    return {"case_reference": "JP.2015500001.A", "document_id": "Abstract_61539913647_JP"}


def test_jpo_frozen_twenty_path_table_routes_domestic_and_opd_separately(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_JPO_BEARER", "offline-token")
    harness = OfflineHarness()
    capabilities = {spec[1] for spec in OPERATIONS.values()}
    adapter = JPOAdapter(harness.context(capabilities), enabled=True, token_env="SYNTHETIC_JPO_BEARER", opd_enabled=True)
    assert len(OPERATIONS) == 20
    for operation in OPERATIONS:
        result = adapter.execute(operation, _jpo_params(operation))
        assert result["status"] == "complete", (operation, result)
    urls = {item["operation"]: item["url"] for item in harness.requests}
    assert urls["app_progress"].startswith("https://ip-data.jpo.go.jp/api/patent/v1/")
    assert urls["opd_family"].startswith("https://ip-data.jpo.go.jp/opdapi/patent/v1/")
    assert len(harness.reservations) == len(harness.requests) == 20
    for request, reservation in zip(harness.requests, harness.reservations):
        assert request["method"] == "GET" and request["allow_redirects"] is False
        assert request["source"] == "jpo" and request["identity"] == IDENTITY
        assert request["capability"] == reservation["capability"]
        assert request["operation"] == reservation["operation"]
        assert request["budget_reservation"]
        assert request["sensitive_headers"] == ["Authorization"]
        assert request["headers"]["Authorization"] == "Bearer offline-token"


def test_jpo_no_keyword_search_pending_activation_and_opd_permission(monkeypatch):
    monkeypatch.delenv("NO_JPO_TOKEN", raising=False)
    harness = OfflineHarness()
    adapter = JPOAdapter(harness.context({"case_progress", "family_lookup"}), enabled=True, token_env="NO_JPO_TOKEN")
    assert adapter.execute("app_progress", {"application_number": "2020008423"})["status"] == "pending_activation"
    assert adapter.execute("opd_family", _jpo_params("opd_family"))["status"] == "pending_activation"
    assert adapter.execute("keyword_search", {"query": "membrane"})["status"] == "unsupported"
    assert adapter.execute("made_up", {})["status"] == "pending_spec"
    assert harness.requests == []


def test_jpo_argument_encoding_validation_business_status_and_http_statuses(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_JPO_BEARER", "offline-token")
    harness = OfflineHarness()
    adapter = JPOAdapter(harness.context({"party_reference", "case_progress"}), enabled=True, token_env="SYNTHETIC_JPO_BEARER")
    malformed = adapter.execute("app_progress", {"application_number": "../../etc"})
    assert malformed["status"] == "error" and harness.requests == []
    control = adapter.execute("applicant_attorney_by_name", {"applicant_name": "valid\nheader"})
    assert control["status"] == "error" and harness.requests == []
    encoded = adapter.execute("applicant_attorney_by_name", {"applicant_name": "A/B"})
    assert encoded["status"] == "complete"
    assert "/A%2FB" in harness.requests[-1]["url"]
    assert harness.requests[-1]["params"] == {}
    for body, expected in ((b'{"result":{"statusCode":"107","data":{}}}', "no_match"), (b'{"result":{"statusCode":"203","data":{}}}', "rate_limited"), (b'{"result":{"statusCode":"208","data":{}}}', "error")):
        harness.content = body
        assert adapter.execute("app_progress", {"application_number": "2020008423"})["status"] == expected
    harness.content, harness.headers = b'<api-data><statusCode>107</statusCode></api-data>', {"content-type": "application/xml"}
    opd_adapter = JPOAdapter(harness.context({"case_progress"}), enabled=True, token_env="SYNTHETIC_JPO_BEARER", opd_enabled=True)
    assert opd_adapter.execute("opd_global_doc_list", _jpo_params("opd_global_doc_list"))["status"] == "no_match"
    assert harness.requests[-1]["url"].startswith("https://ip-data.jpo.go.jp/opdapi/")
    for code, expected in ((404, "no_match"), (401, "permission_required"), (403, "permission_required"), (429, "rate_limited")):
        harness.status, harness.content = code, b""
        assert adapter.execute("app_progress", {"application_number": "2020008423"})["status"] == expected


def test_jpo_budget_body_redirect_and_provenance_boundaries(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_JPO_BEARER", "offline-token")
    denied = OfflineHarness(deny=True)
    adapter = JPOAdapter(denied.context({"case_progress"}), enabled=True, token_env="SYNTHETIC_JPO_BEARER")
    assert adapter.execute("app_progress", {"application_number": "2020008423"})["status"] == "budget_denied"
    assert denied.requests == [] and len(denied.reservations) == 1
    empty = OfflineHarness(content=b"")
    assert JPOAdapter(empty.context({"case_progress"}), enabled=True, token_env="SYNTHETIC_JPO_BEARER").execute("app_progress", {"application_number": "2020008423"})["issues"][0]["code"] == "RH_JPO_EMPTY_BODY"
    evil = OfflineHarness(final_url="https://attacker.invalid/patent", redirect_chain=["https://attacker.invalid/patent"])
    escaped = JPOAdapter(evil.context({"case_progress"}), enabled=True, token_env="SYNTHETIC_JPO_BEARER").execute("app_progress", {"application_number": "2020008423"})
    assert escaped["issues"][0]["code"] == "RH_PATENT_REDIRECT"
    good = OfflineHarness(content=b'{"result":{"statusCode":"100","data":{}}}')
    success = JPOAdapter(good.context({"case_progress"}), enabled=True, token_env="SYNTHETIC_JPO_BEARER").execute("app_progress", {"application_number": "2020008423"})
    assert success["provenance"][0]["content_sha256"] == hashlib.sha256(good.content).hexdigest()
    def identity_guard(**values):
        return False if values["identity"] != IDENTITY else good.reserve(**values)
    wrong_identity = SourceContext(good.request, identity_guard, {**IDENTITY, "task_id": "other"}, frozenset({"case_progress"}))
    before = len(good.requests)
    wrong_result = JPOAdapter(wrong_identity, enabled=True, token_env="SYNTHETIC_JPO_BEARER").execute("app_progress", {"application_number": "2020008423"})
    assert wrong_result["status"] == "budget_denied"
    assert len(good.requests) == before


def test_eps_publication_dates_formats_and_document_variants_are_synthetic(monkeypatch):
    caps = {"publication_date_index", "publication_date_list", "publication_format_lookup", "official_publication_document"}
    harness = OfflineHarness(content=b'<html><a href="https://data.epo.org/publication-server/rest/v1.2/publication-dates/20260204/patents">date</a></html>', headers={"content-type": "text/html"})
    adapter = EPOPublicationAdapter(harness.context(caps), enabled=True)
    dates = adapter.execute("publication_dates", {})
    assert dates["data"]["publication_dates"] == ["20260204"]
    harness.content = b'<html><a href="/publication-server/rest/v1.2/publication-dates/20260204/patents/EP1004359NWB1">EP1004359NWB1</a></html>'
    patents = adapter.execute("patents_for_date", {"publication_date": "20260204"})
    assert patents["data"]["publication_ids"] == ["EP1004359NWB1"]
    harness.content = b'<html><a href="/publication-server/rest/v1.2/patents/EP1004359NWB1/document.xml">XML</a><a href="/publication-server/rest/v1.2/patents/EP1004359NWB1/document.pdf">PDF</a></html>'
    formats = adapter.execute("available_formats", {"publication_id": "EP1004359NWB1"})
    assert formats["data"]["formats"] == ["pdf", "xml"]
    variants = {"xml": b'<ep-patent-document id="EP1004359NWB1"/>', "html": b'<html>EP1004359NWB1 patent description claims</html>', "pdf": b'%PDF-1.7 synthetic', "zip": b'PK\x03\x04synthetic'}
    types = {"xml": "application/xml", "html": "text/html", "pdf": "application/pdf", "zip": "application/zip"}
    for extension, body in variants.items():
        harness.content, harness.headers = body, {"content-type": types[extension]}
        response = adapter.execute("document", {"publication_id": "EP1004359NWB1", "format": extension})
        assert response["status"] == "complete", (extension, response)
        assert response["data"]["content"] == body
        assert response["provenance"][0]["content_sha256"] == hashlib.sha256(body).hexdigest()
    assert all(request["url"].startswith("https://data.epo.org/publication-server/rest/v1.2/") for request in harness.requests)


def test_eps_rejects_bad_dates_numbers_formats_and_handles_empty_body_status():
    harness = OfflineHarness(content=b"")
    adapter = EPOPublicationAdapter(harness.context({"publication_date_list", "official_publication_document"}), enabled=True)
    assert adapter.execute("patents_for_date", {"publication_date": "20260230"})["status"] == "error"
    assert adapter.execute("document", {"publication_id": "EP../../evil", "format": "xml"})["status"] == "error"
    assert adapter.execute("document", {"publication_id": "EP1004359NWB1", "format": "exe"})["status"] == "error"
    assert harness.requests == []
    assert adapter.execute("document", {"publication_id": "EP1004359NWB1", "format": "xml"})["issues"][0]["code"] == "RH_EPS_EMPTY_BODY"
    harness.status = 401
    assert adapter.execute("document", {"publication_id": "EP1004359NWB1", "format": "xml"})["status"] == "permission_required"
    harness.status = 413
    partial = adapter.execute("document", {"publication_id": "EP1004359NWB1", "format": "xml"})
    assert partial["status"] == "partial" and partial["coverage"]["partial"] is True
    assert EPOPublicationAdapter(harness.context({"publication_date_index"}), enabled=False).execute("publication_dates", {})["status"] == "pending_activation"


def test_linked_data_confirmed_item_paths_and_legal_path_pending_spec():
    harness = OfflineHarness(content=b'{"@id":"synthetic","@type":"synthetic"}')
    adapter = EPOLinkedAdapter(harness.context({"application_record", "publication_record", "cpc_vocabulary", "ipc_vocabulary"}), enabled=True)
    for operation, params, expected in (
        ("application", {"authority": "EP", "application_number": "81850042"}, "/doc/application/EP/81850042.json"),
        ("publication", {"st3": "EP", "publication_number": "1048543", "kind": "A1", "publication_date": "-"}, "/data/publication/EP/1048543/A1/-.json"),
        ("classification_cpc", {"symbol": "A01B33/00"}, "/def/cpc/A01B33%2F00.json"),
        ("classification_ipc", {"symbol": "A"}, "/def/ipc/A.json"),
    ):
        response = adapter.execute(operation, params)
        assert response["status"] == "complete"
        assert expected in harness.requests[-1]["url"]
        assert harness.requests[-1]["source"] == "epo_linked"
        assert harness.requests[-1]["identity"] == IDENTITY
    before = len(harness.requests)
    assert adapter.execute("legal_events", {"application_number": "81850042"})["status"] == "pending_spec"
    assert adapter.execute("unknown", {})["status"] == "pending_spec"
    assert len(harness.requests) == before


def test_linked_publication_paging_is_budgeted_and_conservatively_partial():
    harness = OfflineHarness(content=b'{"items":[{"id":"synthetic-publication"}]}')
    adapter = EPOLinkedAdapter(harness.context({"publication_date_filter"}), enabled=True)
    page = adapter.execute("publications_by_date", {"from_date": "2026-01-01", "to_date": "2026-01-31", "page": 2, "page_size": 25})
    assert page["status"] == "partial"
    assert page["coverage"] == {"complete": False, "partial": True, "next_page": 3}
    assert harness.requests[0]["params"] == {"min-publicationDate": "2026-01-01", "max-publicationDate": "2026-01-31", "_page": 2, "_pageSize": 25}
    assert len(harness.reservations) == 1
    bad = adapter.execute("publications_by_date", {"from_date": "2026-02-01", "to_date": "2026-01-01", "page": 0, "page_size": 201})
    assert bad["status"] == "error"
    assert len(harness.requests) == 1


def test_linked_redirect_size_http_and_body_validation_are_visible():
    denied_redirect = OfflineHarness(final_url="https://example.invalid/doc/application/EP/123.json")
    adapter = EPOLinkedAdapter(denied_redirect.context({"application_record"}), enabled=True)
    result = adapter.execute("application", {"authority": "EP", "application_number": "123"})
    assert result["issues"][0]["code"] == "RH_PATENT_REDIRECT"
    too_large = OfflineHarness(content=b"x" * 2048, headers={"content-type": "application/json"})
    oversized = EPOLinkedAdapter(too_large.context({"application_record"}, max_response_bytes=100), enabled=True).execute("application", {"authority": "EP", "application_number": "123"})
    assert oversized["issues"][0]["code"] == "RH_PATENT_SIZE_LIMIT"
    invalid = OfflineHarness(content=b"{bad", headers={"content-type": "application/json"})
    malformed = EPOLinkedAdapter(invalid.context({"application_record"}), enabled=True).execute("application", {"authority": "EP", "application_number": "123"})
    assert malformed["issues"][0]["code"] == "RH_PATENT_INVALID_BODY"
    invalid.status = 429
    assert EPOLinkedAdapter(invalid.context({"application_record"}), enabled=True).execute("application", {"authority": "EP", "application_number": "123"})["status"] == "rate_limited"


def test_request_once_fails_closed_before_physical_request_for_bad_capability_url_or_reservation():
    harness = OfflineHarness()
    from research_harness.patent_sources.contracts import request_once, SourceFailure
    harness.reserve = lambda **kwargs: None
    ctx = harness.context({"case_progress"})
    kwargs = dict(source="jpo", operation="app_progress", capability="case_progress", method="GET",
                  headers={}, allowed_hosts=("ip-data.jpo.go.jp",), allowed_path_prefixes=("/api/patent/v1/",))
    for overrides, code in (({"url": "https://attacker.invalid/api/patent/v1/x"}, "RH_PATENT_URL"),
                            ({"url": "https://ip-data.jpo.go.jp/api/patent/v1/x", "capability": "other"}, "RH_PATENT_CAPABILITY")):
        with pytest.raises(SourceFailure) as caught:
            request_once(ctx, url=overrides.pop("url"), **{**kwargs, **overrides})
        assert caught.value.code == code
    with pytest.raises(SourceFailure) as caught:
        request_once(ctx, url="https://ip-data.jpo.go.jp/api/patent/v1/x", **kwargs)
    assert caught.value.code == "RH_PATENT_BUDGET"
    assert harness.requests == []


def test_jpo_missing_status_unknown_content_and_bad_binary_are_not_complete(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_JPO_BEARER", "offline-token")
    harness = OfflineHarness(content=b'{"result":{"data":{}}}')
    adapter = JPOAdapter(harness.context({"case_progress", "application_documents"}), enabled=True, token_env="SYNTHETIC_JPO_BEARER")
    assert adapter.execute("app_progress", {"application_number": "2020008423"})["status"] == "partial"
    harness.content, harness.headers = b"{}", {"content-type": "text/plain"}
    assert adapter.execute("app_progress", {"application_number": "2020008423"})["status"] == "error"
    harness.content, harness.headers = b"not-a-zip", {"content-type": "application/zip"}
    assert adapter.execute("application_documents", {"application_number": "2020008423"})["issues"][0]["code"] == "RH_JPO_BINARY_SIGNATURE"


def test_eps_index_and_document_identity_fail_closed():
    caps = {"publication_date_index", "publication_date_list", "official_publication_document"}
    harness = OfflineHarness(content=b"garbled", headers={"content-type": "text/html"})
    adapter = EPOPublicationAdapter(harness.context(caps), enabled=True)
    assert adapter.execute("publication_dates", {})["status"] == "partial"
    harness.content = b'<html><a href="https://attacker.invalid/publication-server/rest/v1.2/publication-dates/20260101/patents">x</a></html>'
    assert adapter.execute("publication_dates", {})["issues"][0]["code"] == "RH_EPS_EXTERNAL_INDEX_LINK"
    harness.content, harness.headers = b'<ep-patent-document id="EP9999999NWB1"/>', {"content-type": "application/xml"}
    wrong = adapter.execute("document", {"publication_id": "EP1004359NWB1", "format": "xml"})
    assert wrong["status"] == "partial" and wrong["issues"][0]["code"] == "RH_EPS_IDENTITY_MISMATCH"
