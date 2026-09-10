from pathlib import Path
import asyncio
import os
import subprocess
import sys

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


def protocol_probe():
    """Exercise the real SDK over a child-process STDIO transport."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    child_code = (
        "from research_harness.rag_mcp import RagMCPServer, create_mcp_server\n"
        "class F:\n"
        "  def import_library(self, catalog, *, limit=None): return {'outcome':'completed','imported':0,'reused':0,'failed':0}\n"
        "  def search_evidence(self, query, *, top_k=8, filters=None): return {'query':query,'items':[],'snapshot_version_ids':[],'diagnostics':{'mode':'hybrid'}}\n"
        "  def get_evidence_context(self, evidence_id, *, before=1, after=1): return {'evidence_id':evidence_id,'items':[]}\n"
        "  def get_document(self, document_id): raise ValueError('secret path leaked')\n"
        "  def get_library_status(self): return {'document_count':0}\n"
        "rag=RagMCPServer('.', 'catalog.json', library=F()); create_mcp_server(rag).run(transport='stdio')"
    )
    child = f"exec({child_code!r})"

    async def run():
        pythonpath = os.path.abspath("src") + os.pathsep + os.environ.get("PYTHONPATH", "")
        params = StdioServerParameters(command=sys.executable, args=["-c", child], env={**os.environ, "PYTHONPATH": pythonpath})
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                assert names == {"import_library", "search_evidence", "get_evidence_context", "get_document", "get_library_status"}
                ok = await session.call_tool("search_evidence", {"query": "membrane", "top_k": 1})
                assert not ok.is_error
                failed = await session.call_tool("get_document", {"document_id": "secret"})
                assert not failed.is_error
                assert failed.structured_content["error"]["code"] == "RH_RAG_INTERNAL"
                assert "secret path" not in str(failed.structured_content)

    asyncio.run(run())
    print("real-mcp-stdio: PASS (initialize/list_tools/call_tool + safe failure)")
