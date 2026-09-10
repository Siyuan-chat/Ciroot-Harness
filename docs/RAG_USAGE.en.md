# Local RAG MCP

This is a local STDIO MCP adapter. It delegates to `research_harness.rag.RagLibrary`; it does not read Codex credentials, call a generation model, or provide HTTP/UI.

## Short local sequence

Set `RAG_MODEL_CACHE` and `HF_HOME` as described in [RAG_RUNTIME.md](RAG_RUNTIME.md), install into one virtual environment, finish the long CLI import, then register MCP for the same workspace. `--env` persists the caches for the Codex-launched service; shell variables alone do not:

```powershell
python -m venv .venv
$py = (Resolve-Path .venv\Scripts\python.exe)
$repo = (Get-Location).Path
$modelCache = Join-Path $repo ".local\rag-runtime\models"
$hfHome = Join-Path $repo ".local\rag-runtime\huggingface"
New-Item -ItemType Directory -Force -Path $modelCache, $hfHome | Out-Null
$modelCache = (Resolve-Path $modelCache).Path
$hfHome = (Resolve-Path $hfHome).Path
$env:RAG_MODEL_CACHE = $modelCache
$env:HF_HOME = $hfHome
& $py -m pip install ".[rag-mcp]"
& $py -m research_harness.rag --workspace C:\data\rag-workspace import C:\data\catalog.json
& $py -m research_harness.rag --workspace C:\data\rag-workspace search "crosslinking swelling"
codex mcp add research-harness-rag --env "RAG_MODEL_CACHE=$modelCache" --env "HF_HOME=$hfHome" -- $py -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

See [RAG_STAGE.md](RAG_STAGE.md). Generation-model API mode is contract-only; real 23-document acceptance remains pending.

Prepare a writable workspace and a catalog whose `records[].file` entries are PDF/TXT paths relative to the catalog directory. Paths escaping that directory are rejected; the source directory remains read-only. Workspace and catalog are fixed at startup and cannot be supplied by tools.

First model startup can exceed ordinary tool timeouts. After registration, add these native Codex settings inside the existing `[mcp_servers.research-harness-rag]` section in `~/.codex/config.toml` (do not create a second section):

```toml
startup_timeout_sec = 120
tool_timeout_sec = 600
```

`examples/rag-mcp.windows.json` is for other hosts that accept that JSON format. Direct launch:

```powershell
& $py -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

The five tools are `import_library(limit?)`, `search_evidence(query, top_k?, filters?)`, `get_evidence_context(evidence_id, before?, after?)`, `get_document(document_id)`, and `get_library_status()`. Import is the only write tool. Failures return `{ "error": { "code", "message" } }` without low-level exception text or secrets.

Actual parser, embedding, index, and coverage support comes from RagLibrary. The protocol tests use an explicit fake service; they do not establish real PDF, multilingual retrieval, or Codex-host acceptance.

MCP is a single-process serial service; initial model loading and imports block that process. Use the CLI for long imports, and do not run a CLI import while MCP has the same workspace open.

After the core service has imported documents, run `real_service_probe(python_executable, workspace, catalog)` for a real STDIO check; it does not import. Record this evidence separately from the fake protocol test.
