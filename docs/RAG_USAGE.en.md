# Local RAG MCP

This is a local STDIO MCP adapter. It delegates to `research_harness.rag.RagLibrary`; it does not read Codex credentials, call a generation model, or provide HTTP/UI.

Install the project and the MCP Python SDK in the environment supplied by Terra. Prepare a writable workspace and a catalog whose `records[].file` entries point to permitted local PDF/TXT files. Workspace and catalog are fixed at startup and cannot be supplied by tools.

Copy `examples/rag-mcp.windows.json` into the host MCP configuration and replace the Python, workspace, and catalog paths. Direct launch:

```powershell
python -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

The five tools are `import_library(limit?)`, `search_evidence(query, top_k?, filters?)`, `get_evidence_context(evidence_id, before?, after?)`, `get_document(document_id)`, and `get_library_status()`. Import is the only write tool. Failures return `{ "error": { "code", "message" } }` without low-level exception text or secrets.

Actual parser, embedding, index, and coverage support comes from RagLibrary. The protocol tests use an explicit fake service; they do not establish real PDF, multilingual retrieval, or Codex-host acceptance.
