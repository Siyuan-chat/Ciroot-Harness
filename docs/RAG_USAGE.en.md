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
& $py -m research_harness.rag --workspace C:\data\rag-workspace search "crosslinking methods reduce membrane swelling"
codex mcp add research-harness-rag --env "RAG_MODEL_CACHE=$modelCache" --env "HF_HOME=$hfHome" -- $py -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

See [RAG_STAGE.md](RAG_STAGE.md) and the [independent acceptance record](RAG_ACCEPTANCE.md). Generation-model API mode is contract-only.

`prepare` only creates or reuses parse-cache entries; it does not create evidence or vectors. `rebuild` migrates vectors from already stored evidence without parsing sources: `& $py -m research_harness.rag --workspace C:\data\rag-workspace rebuild`. Run either long operation while MCP is closed for that workspace. Ask in Chinese or Japanese through Codex; the host may plan an English retrieval expression before calling the local search.

Search ranks dense cosine and BM25 lexical candidates with fixed reciprocal-rank fusion. BM25 uses the same token stream as filtering, including CJK n-grams and English stemming; no per-question stopword list or ranking parameter is configured.

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

When the corpus is English and the question is in Chinese or Japanese, the host model may generate a concise English retrieval query from the original request while retaining the original question for the answer. Do not use a hard-coded translation table or guess facts or numbers. For a complete, unique paper title, use DOI or document filters instead of putting the title into a topical query. Find direct evidence first, then read context. Direct Chinese/Japanese cross-language vector retrieval has not been accepted here and must not be claimed as passed.

After the core service has imported documents, run `real_service_probe(python_executable, workspace, catalog)` for a real STDIO check; it does not import. Record this evidence separately from the fake protocol test.
