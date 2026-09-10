# Local RAG MCP

This is a local STDIO MCP adapter. It delegates to `research_harness.rag.RagLibrary`; it does not read Codex credentials, call a generation model, or provide HTTP/UI.

Install the project and MCP Python SDK (for example, the project's `.[rag,mcp]` extras when available). Prepare a writable workspace and a catalog whose `records[].file` entries are PDF/TXT paths relative to the catalog directory. Paths escaping that directory are rejected; the source directory remains read-only. Workspace and catalog are fixed at startup and cannot be supplied by tools.

Register it in Codex CLI (replace paths):

```powershell
codex mcp add research-harness-rag -- C:\path\to\.venv\Scripts\python.exe -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

`examples/rag-mcp.windows.json` is for other hosts that accept that JSON format. Direct launch:

```powershell
python -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

The five tools are `import_library(limit?)`, `search_evidence(query, top_k?, filters?)`, `get_evidence_context(evidence_id, before?, after?)`, `get_document(document_id)`, and `get_library_status()`. Import is the only write tool. Failures return `{ "error": { "code", "message" } }` without low-level exception text or secrets.

Actual parser, embedding, index, and coverage support comes from RagLibrary. The protocol tests use an explicit fake service; they do not establish real PDF, multilingual retrieval, or Codex-host acceptance.
