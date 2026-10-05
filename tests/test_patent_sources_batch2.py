"""Offline USPTO/Pearl adapter contracts. No real patent requests are made."""
import json

from research_harness.patent_sources.contracts import SourceContext
from research_harness.patent_sources.pearl import PearlAdapter
from research_harness.patent_sources.uspto import USPTOAdapter


IDENTITY = {"run_id": "synthetic-run", "task_id": "synthetic-task", "task_version": 1}


class Harness:
    def __init__(self, body=None, *, status=200, content_type="application/json", final_url=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body if body is not None else {"count": 1, "patentFileWrapperDataBag": []}).encode()
        self.status, self.content_type, self.final_url = status, content_type, final_url
        self.requests = []

    def reserve(self, **values):
        return "synthetic-budget-token"

    def request(self, request):
        self.requests.append(request)
        return {"status_code": self.status, "headers": {"content-type": self.content_type}, "content": self.body,
                "url": self.final_url or request["url"], "redirect_chain": [], "request_identifier": "synthetic-http"}

    def context(self, capabilities, max_response_bytes=4096):
        return SourceContext(self.request, self.reserve, dict(IDENTITY), frozenset(capabilities), max_response_bytes)


def _record(**extra):
    return {"applicationNumberText": "18045436", **extra}


def test_uspto_pending_activation_and_operation_routes(monkeypatch):
    monkeypatch.delenv("TEST_ODP_KEY", raising=False)
    h = Harness()
    adapter = USPTOAdapter(h.context({"patent_search", "application_record"}), enabled=True, api_key_env="TEST_ODP_KEY")
    assert adapter.execute("search_get", {"q": "membrane"})["status"] == "pending_activation"
    monkeypatch.setenv("TEST_ODP_KEY", "synthetic-key")
    data = {"count": 1, "patentFileWrapperDataBag": [_record(applicationMetaData={"earliestPublicationNumber": "US20250001234A1", "patentNumber": "12000000"})]}
    h.body = json.dumps(data).encode()
    response = adapter.execute("metadata", {"application_number": "18045436"})
    assert response["status"] == "complete"
    request = h.requests[-1]
    assert request["url"] == "https://api.uspto.gov/api/v1/patent/applications/18045436/meta-data"
    assert request["headers"]["X-API-KEY"] == "synthetic-key"
    assert request["sensitive_headers"] == ["X-API-KEY"]
    projection = response["data"]["records"][0]
    assert projection["application_number"] == "18045436"
    assert projection["publication_number"] == "US20250001234A1"
    assert projection["patent_number"] == "12000000"
    assert len(h.requests) == 1


def test_uspto_get_post_schemas_and_explicit_pagination(monkeypatch):
    monkeypatch.setenv("TEST_ODP_KEY", "synthetic-key")
    records = [_record(applicationMetaData={}) for _ in range(2)]
    h = Harness({"count": 17, "patentFileWrapperDataBag": records})
    adapter = USPTOAdapter(h.context({"patent_search"}), enabled=True, api_key_env="TEST_ODP_KEY")
    get_result = adapter.execute("search_get", {"q": "Utility AND Design", "offset": 10, "limit": 2, "fields": "applicationNumberText"})
    assert get_result["status"] == "partial"
    assert get_result["coverage"]["next_offset"] == 12
    assert get_result["coverage"]["reported_count_semantics"] == "unspecified_by_frozen_schema"
    assert h.requests[-1]["params"] == {"q": "Utility AND Design", "offset": 10, "limit": 2, "fields": "applicationNumberText"}
    post_result = adapter.execute("search_post", {"q": "Utility", "pagination": {"offset": 4, "limit": 5},
                                                  "filters": [{"name": "applicationMetaData.applicationTypeLabelName", "value": ["Utility"]}],
                                                  "rangeFilters": [{"field": "applicationMetaData.filingDate", "valueFrom": "2020-01-01", "valueTo": "2021-01-01"}],
                                                  "sort": [{"field": "applicationMetaData.filingDate", "order": "desc"}], "fields": ["applicationNumberText"]})
    assert post_result["coverage"]["offset"] == 4
    assert h.requests[-1]["method"] == "POST"
    assert h.requests[-1]["headers"]["Content-Type"] == "application/json"
    assert json.loads(h.requests[-1]["body"])['pagination'] == {"offset": 4, "limit": 5}
    before = len(h.requests)
    assert adapter.execute("search_post", {"pagination": {"cursor": "invented"}})["status"] == "error"
    assert adapter.execute("search_get", {"magic": "bad"})["status"] == "error"
    assert len(h.requests) == before


def test_uspto_schema_empty_success_statuses_and_truncation(monkeypatch):
    monkeypatch.setenv("TEST_ODP_KEY", "synthetic-key")
    h = Harness({})
    adapter = USPTOAdapter(h.context({"patent_search", "application_record"}), enabled=True, api_key_env="TEST_ODP_KEY")
    assert adapter.execute("search_get", {})["status"] == "partial"
    h.body = b'{"count":0,"patentFileWrapperDataBag":[]}'
    assert adapter.execute("search_get", {})["status"] == "no_match"
    h.body = json.dumps({"count": 1, "patentFileWrapperDataBag": [_record(assignmentBag="invalid-type")]}).encode()
    assert adapter.execute("assignment", {"application_number": "18045436"})["status"] == "partial"
    h.body = b'{"count":0,"patentFileWrapperDataBag":[]}'
    for code, expected in ((401, "permission_required"), (403, "permission_required"), (429, "rate_limited")):
        h.status, h.body = code, b""
        assert adapter.execute("search_get", {})["status"] == expected
    h.status, h.body = 200, b""
    assert adapter.execute("search_get", {})["status"] == "partial"
    before = len(h.requests)
    denied_ctx = SourceContext(h.request, lambda **kwargs: None, dict(IDENTITY), frozenset({"patent_search"}))
    denied = USPTOAdapter(denied_ctx, enabled=True, api_key_env="TEST_ODP_KEY").execute("search_get", {})
    assert denied["status"] == "budget_denied" and len(h.requests) == before
    h.status = 200
    h.body = json.dumps({"count": -1, "patentFileWrapperDataBag": []}).encode()
    negative = adapter.execute("search_get", {})
    assert negative["status"] == "partial" and negative["issues"][0]["code"] == "RH_USPTO_SCHEMA"


def test_uspto_search_last_short_page_keeps_count_semantics_unconfirmed(monkeypatch):
    monkeypatch.setenv("TEST_ODP_KEY", "synthetic-key")
    h = Harness({"count": 17, "patentFileWrapperDataBag": [_record(applicationMetaData={})]})
    adapter = USPTOAdapter(h.context({"patent_search"}), enabled=True, api_key_env="TEST_ODP_KEY")
    last = adapter.execute("search_get", {"offset": 16, "limit": 2})
    assert last["status"] == "partial"
    assert last["coverage"]["reported_count_semantics"] == "unspecified_by_frozen_schema"
    assert "next_offset" not in last["coverage"]
    assert last["issues"][0]["code"] == "RH_USPTO_TOTAL_UNCONFIRMED"


def test_uspto_search_duplicate_missing_and_unprojectable_identity_are_visible(monkeypatch):
    monkeypatch.setenv("TEST_ODP_KEY", "synthetic-key")
    repeated = _record(applicationMetaData={})
    h = Harness({"count": 2, "patentFileWrapperDataBag": [repeated, dict(repeated)]})
    adapter = USPTOAdapter(h.context({"patent_search"}), enabled=True, api_key_env="TEST_ODP_KEY")
    duplicate = adapter.execute("search_get", {"limit": 10})
    assert duplicate["status"] == "partial"
    assert any(i["code"] == "RH_USPTO_DUPLICATE_IDENTITY" for i in duplicate["issues"])
    h.body = json.dumps({"count": 1, "patentFileWrapperDataBag": [{"foo": "bar"}]}).encode()
    unknown = adapter.execute("search_get", {"limit": 10, "fields": "foo"})
    assert unknown["status"] == "partial"
    assert unknown["data"]["raw"]["patentFileWrapperDataBag"] == [{"foo": "bar"}]
    assert unknown["data"]["records"] == [{}]
    assert {i["code"] for i in unknown["issues"]} >= {"RH_USPTO_IDENTITY_INSUFFICIENT", "RH_USPTO_PROJECTION_EMPTY"}


def test_uspto_file_download_allowlist_origin_bound_credentials_and_size(monkeypatch):
    monkeypatch.setenv("TEST_ODP_KEY", "synthetic-key")
    h = Harness(b"%PDF-1.7 offline fixture", content_type="application/pdf")
    adapter = USPTOAdapter(h.context({"document_download"}), enabled=True, api_key_env="TEST_ODP_KEY")
    evil = adapter.download_file("https://attacker.invalid/file.pdf")
    assert evil["status"] == "error" and h.requests == []
    bulk_url = "https://bulkdata.uspto.gov/data/patent/application/redbook/fulltext/2024/ipa240104.zip"
    h.body, h.content_type = b"PK\x03\x04synthetic", "application/zip"
    downloaded = adapter.download_file(bulk_url)
    assert downloaded["status"] == "complete"
    assert "X-API-KEY" not in h.requests[-1]["headers"]
    h.body, h.content_type = b"%PDF-1.7 synthetic", "application/pdf"
    assignment_url = "https://legacy-assignments.uspto.gov/assignments/assignment-pat-060620-0769.pdf"
    assert adapter.download_file(assignment_url)["status"] == "complete"
    assert "X-API-KEY" not in h.requests[-1]["headers"]
    api_url = "https://api.uspto.gov/api/v1/download/applications/18045436/DOCPDF.pdf"
    h.body, h.content_type = b"%PDF-1.7 synthetic", "application/pdf"
    assert adapter.download_file(api_url)["status"] == "complete"
    assert h.requests[-1]["headers"]["X-API-KEY"] == "synthetic-key"
    blocked = adapter.download_file("https://api.uspto.gov/other/download/file.pdf")
    assert blocked["status"] == "error" and len(h.requests) == 3
    traversal = adapter.download_file("https://api.uspto.gov/api/v1/download/applications/../x/evil.pdf")
    assert traversal["status"] == "error" and len(h.requests) == 3
    malformed = adapter.download_file("https://[invalid/file.pdf")
    assert malformed["status"] == "error" and len(h.requests) == 3


def test_uspto_document_download_reports_bad_body_and_documents_route(monkeypatch):
    monkeypatch.setenv("TEST_ODP_KEY", "synthetic-key")
    h = Harness(b"", content_type="application/pdf")
    adapter = USPTOAdapter(h.context({"application_record", "document_download"}), enabled=True, api_key_env="TEST_ODP_KEY")
    empty = adapter.download_file("https://api.uspto.gov/api/v1/download/applications/18045436/ABC.pdf")
    assert empty["status"] == "partial" and empty["issues"][0]["code"] == "RH_USPTO_EMPTY_BODY"
    h.body = json.dumps({"count": 3, "documentBag": [
        {"applicationNumberText": "18045436", "documentIdentifier": "ABC", "documentCode": "WFEE", "officialDate": "2024-01-01", "downloadOptionBag": [{"mimeTypeIdentifier": "PDF", "downloadUrl": "https://api.uspto.gov/api/v1/download/applications/18045436/ABC.pdf"}]},
        {"applicationNumberText": "18045436", "documentIdentifier": "DEF", "documentCode": "IDS", "officialDate": "2024-01-02", "downloadOptionBag": []},
        {"applicationNumberText": "18045436", "documentIdentifier": "GHI", "documentCode": "PE", "officialDate": "2024-01-03", "downloadOptionBag": []},
    ]}).encode()
    h.content_type = "application/json"
    response = adapter.execute("documents", {"application_number": "18045436"})
    assert response["status"] == "complete"
    assert response["coverage"]["returned_count"] == 3
    assert response["data"]["record_key"] == "documentBag"
    assert len(response["data"]["records"]) == 3
    assert "pagination" not in response["data"]
    assert h.requests[-1]["url"].endswith("/applications/18045436/documents")


def test_uspto_all_documented_application_facets_use_official_routes(monkeypatch):
    monkeypatch.setenv("TEST_ODP_KEY", "synthetic-key")
    h = Harness()
    adapter = USPTOAdapter(h.context({"application_record"}), enabled=True, api_key_env="TEST_ODP_KEY")
    expected = {
        "application_details": {"applicationMetaData": {}}, "metadata": {"applicationMetaData": {}}, "adjustment": {"patentTermAdjustmentData": {}},
        "assignment": {"assignmentBag": []}, "attorney": {"recordAttorney": {}}, "continuity": {"parentContinuityBag": [], "childContinuityBag": []},
        "foreign_priority": {"foreignPriorityBag": []}, "transactions": {"eventDataBag": []}, "associated_documents": {"pgpubDocumentMetaData": {}},
    }
    for operation, keys in expected.items():
        h.body = json.dumps({"count": 1, "patentFileWrapperDataBag": [{"applicationNumberText": "PCTUS0719317", **keys}]}).encode()
        response = adapter.execute(operation, {"application_number": "PCTUS0719317"})
        assert response["status"] == "complete", (operation, response)
        assert h.requests[-1]["url"].endswith("/PCTUS0719317" + {"application_details": "", "metadata": "/meta-data", "adjustment": "/adjustment", "assignment": "/assignment", "attorney": "/attorney", "continuity": "/continuity", "foreign_priority": "/foreign-priority", "transactions": "/transactions", "associated_documents": "/associated-documents"}[operation])
    h.body = json.dumps({"count": 1, "patentFileWrapperDataBag": [{"applicationNumberText": "PCTUS0719317", "applicationMetaData": {}}]}).encode()
    mismatch = adapter.execute("application_details", {"application_number": "18045436"})
    assert mismatch["status"] == "partial" and mismatch["issues"][0]["code"] == "RH_USPTO_WRONG_IDENTITY"
    assert mismatch["data"]["raw"]["patentFileWrapperDataBag"][0]["applicationNumberText"] == "PCTUS0719317"


def test_pearl_is_diagnostic_pending_only_without_guessed_routes():
    h = Harness()
    disabled = PearlAdapter(h.context({"terminology_search"}), enabled=False, spec_configured=False)
    assert disabled.execute("term_search", {"term": "membrane"})["status"] == "pending_activation"
    enabled = PearlAdapter(h.context({"terminology_search"}), enabled=True, spec_configured=False)
    assert enabled.execute("term_search", {"term": "membrane"})["status"] == "pending_spec"
    assert enabled.execute("multilingual_search", {"term": "membrane", "languages": ["en", "ja"]})["status"] == "pending_spec"
    assert enabled.execute("record_query", {"record_id": "x"})["status"] == "pending_spec"
    assert enabled.diagnose()["operations"]["term_search"]["status"] == "pending_spec"
    assert enabled.diagnose()["official_reference"] == "https://www.wipo.int/en/web/wipo-pearl/w/news/2026/wipo-pearl-api-for-terminology-now-available-in-a-new-platform"
    assert enabled.diagnose()["platform_entry"] == "https://b2b.wipo.int"
    denied = PearlAdapter(h.context(set()), enabled=True)
    assert denied.execute("term_search", {"term": "membrane"})["status"] == "unsupported"
    assert denied.diagnose()["capability_granted"] is False
    assert h.requests == []
