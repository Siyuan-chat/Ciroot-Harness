from pathlib import Path

from research_harness.rag_mcp import RagMCPServer


class FakeRag:
    def __init__(self):
        self.calls = []

    def import_library(self, catalog, *, limit=None):
        self.calls.append(("import_library", catalog, limit))
        return {"outcome": "completed", "imported": 1, "reused": 0, "failed": 0}

    def search_evidence(self, query, *, top_k=8, filters=None):
        self.calls.append(("search_evidence", query, top_k, filters))
        return {"query": query, "items": [], "snapshot_version_ids": [], "diagnostics": {"mode": "hybrid"}}

    def get_evidence_context(self, evidence_id, *, before=1, after=1):
        self.calls.append(("get_evidence_context", evidence_id, before, after))
        return {"evidence_id": evidence_id, "items": []}

    def get_document(self, document_id):
        self.calls.append(("get_document", document_id))
        return {"document_id": document_id}

    def get_library_status(self):
        self.calls.append(("get_library_status",))
        return {"document_count": 0}

    def close(self):
        self.calls.append(("close",))


class SafeFailure(FakeRag):
    def get_document(self, document_id):
        raise RuntimeError(f"private path: {document_id}")


def test_tools_delegate_to_configured_service_and_catalog():
    fake = FakeRag()
    adapter = RagMCPServer(".", "catalog.json", library=fake)

    assert adapter.import_library(limit=3)["outcome"] == "completed"
    assert adapter.search_evidence("membrane", top_k=4, filters={"year_min": 2020})["query"] == "membrane"
    assert adapter.get_evidence_context("ev-1", before=0, after=2)["evidence_id"] == "ev-1"
    assert adapter.get_document("doc-1")["document_id"] == "doc-1"
    assert adapter.get_library_status()["document_count"] == 0

    assert fake.calls[0][0] == "import_library"
    assert fake.calls[0][1] == Path("catalog.json").resolve()
    assert fake.calls[0][2] == 3


def test_errors_are_structured_and_do_not_leak_exception_text():
    adapter = RagMCPServer(".", "catalog.json", library=SafeFailure())
    result = adapter.get_document("secret.pdf")
    assert result == {"error": {"code": "RH_RAG_INTERNAL", "message": "operation failed"}}
    assert "secret.pdf" not in str(result)


def test_close_delegates_without_exposing_close_tool():
    fake = FakeRag()
    adapter = RagMCPServer(".", "catalog.json", library=fake)
    adapter.close()
    assert fake.calls == [("close",)]
