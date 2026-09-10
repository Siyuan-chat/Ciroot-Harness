# Local RAG MCP

This is a local STDIO MCP adapter. It delegates to `research_harness.rag.RagLibrary`; it does not read Codex credentials, call a generation model, or provide HTTP/UI.

## Short local sequence

Set `RAG_MODEL_CACHE` and `HF_HOME` as described in [RAG_RUNTIME.md](RAG_RUNTIME.md), install `.[rag-mcp]`, finish the long CLI import, then register MCP for the same workspace:

```powershell
$env:RAG_MODEL_CACHE = "$PWD\.local\rag-runtime\models"
$env:HF_HOME = "$PWD\.local\rag-runtime\huggingface"
python -m pip install ".[rag-mcp]"
python -m research_harness.rag --workspace C:\data\rag-workspace import C:\data\catalog.json
python -m research_harness.rag --workspace C:\data\rag-workspace search "crosslinking swelling"
codex mcp add research-harness-rag -- C:\path\to\.venv\Scripts\python.exe -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

See [RAG_STAGE.md](RAG_STAGE.md). Generation-model API mode is contract-only; real 23-document acceptance remains pending.

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

MCP is a single-process serial service; initial model loading and imports block that process. Use the CLI for long imports, and do not run a CLI import while MCP has the same workspace open.

After the core service has imported documents, run `real_service_probe(python_executable, workspace, catalog)` for a real STDIO check; it does not import. Record this evidence separately from the fake protocol test.
