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


def real_service_probe(python_executable, workspace, catalog):
    """Probe an installed real RagLibrary through the MCP STDIO boundary.

    This deliberately performs no import.  It is an acceptance helper for a
    workspace that has already been populated by the RAG core implementation.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def run():
        env_keys = ("RAG_MODEL_CACHE", "HF_HOME", "HF_HUB_OFFLINE", "HF_HUB_DISABLE_IMPLICIT_TOKEN", "PYTHONIOENCODING")
        child_env = {key: os.environ[key] for key in env_keys if key in os.environ}
        params = StdioServerParameters(
            command=str(python_executable),
            args=["-m", "research_harness.rag_mcp", "--workspace", str(workspace), "--catalog", str(catalog)],
            env=child_env,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                assert names == [
                    "import_library", "search_evidence", "get_evidence_context", "get_document", "get_library_status"
                ]
                status = await session.call_tool("get_library_status", {})
                search = await session.call_tool("search_evidence", {"query": "交联阴离子交换膜", "top_k": 2})
                status_data = status.structured_content or {}
                search_data = search.structured_content or {}
                assert "error" not in status_data, status_data
                assert "error" not in search_data, search_data
                items = search_data.get("items", [])
                assert items, "real service returned no evidence items"
                result = {
                    "tools": names,
                    "status": {key: status_data.get(key) for key in ("document_count", "version_count", "evidence_count", "indexed_document_count")},
                    "search": {"query": search_data.get("query"), "item_count": len(search_data.get("items", [])), "diagnostics": search_data.get("diagnostics")},
                    "context": None,
                    "document": None,
                    "invalid_filter_error": None,
                }
                evidence_id = items[0]["evidence_id"]
                document_id = items[0]["document_id"]
                version_id = items[0]["version_id"]
                context = await session.call_tool("get_evidence_context", {"evidence_id": evidence_id})
                document = await session.call_tool("get_document", {"document_id": document_id})
                context_data = context.structured_content or {}
                document_data = document.structured_content or {}
                assert "error" not in context_data, context_data
                assert "error" not in document_data, document_data
                assert context_data.get("evidence_id") == evidence_id
                context_items = context_data.get("items", [])
                assert context_items and all(item.get("document_id") == document_id and item.get("version_id") == version_id for item in context_items)
                assert document_data.get("document_id") == document_id
                result["context"] = {"ok": True, "item_count": len(context_items)}
                result["document"] = {"ok": True, "document_id": document_id}
                invalid = await session.call_tool("search_evidence", {"query": "test", "filters": {"unknown": True}})
                result["invalid_filter_error"] = (invalid.structured_content or {}).get("error")
                assert result["invalid_filter_error"] and result["invalid_filter_error"]["code"] == "RH_RAG_INVALID_INPUT"
                return result

    result = asyncio.run(run())
    print({"real_service_probe": result})
    return result
