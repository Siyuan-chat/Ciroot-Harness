# Research Harness

[中文](README.zh-CN.md) · English · [日本語](README.ja.md)

A local literature/patent investigation framework. The target workflow is natural-language requirements → versioned JSON → retrieval → comparison with a frozen reference library → human review and reports.

**D2 fixture framework independently accepted on 2026-09-09.** See the [acceptance report](docs/FRAMEWORK_ACCEPTANCE.md). The demo uses synthetic text and local source/model callables. It runs real LangGraph, SQLite and citation verification, producing Chinese, English and Japanese reports. It needs no API keys and makes no external API calls.

## Quick start

Python 3.11+ is required. In a Windows source checkout:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .
.venv\Scripts\rh demo --workspace .local\demo
.venv\Scripts\rh status --workspace .local\demo
```

Installation downloads the declared dependencies; the demo itself is offline. On macOS/Linux use `.venv/bin/python` and `.venv/bin/rh`; independent runtime acceptance currently targets Windows.

The default demo produces two synthetic candidates, verified findings, one human-review issue, three HTML reports, three Markdown reports, canonical JSON and review CSV. Open the returned report directory to read the HTML.

## Available now

- Validated ResearchSpec, automatic revisions for manual edits and frozen run inputs.
- Local text originals/evidence, separate reference snapshots and discoveries.
- Replaceable fixture source/model callables in a minimal LangGraph workflow.
- Citation ownership/quote checks, persistent review decisions, candidate limits and explicit partial/failed outcomes.
- Shared Python services with structured results, safe errors, artifact references and progress callbacks for a future GUI.

Real model/source APIs, OpenAlex/EPO, production vector RAG, PDF/OCR, standalone chat, recovery and GUI are **not integrated in D2**. Installing optional dependencies does not enable them. Unsupported live/chat paths are refused; `lexical_test_only` is retained only for test compatibility. The host assistant currently clarifies requirements and supplies JSON.

[English guide](docs/USER_GUIDE.en.md) · [Current scope](docs/SCOPE_AUDIT.md) · [Contracts/adapters](docs/CONTRACTS.md) · [Acceptance K01–K07](docs/ACCEPTANCE.md) · [Requirements](docs/PRD.md) · [Architecture](docs/ARCHITECTURE.md) · [Decisions](docs/DECISIONS.md)

The first later case is polymer design. [Its draft](examples/polymer-design.draft.json) has unresolved requirements and is not runnable scientific evidence. Real API integration and case/demo validation precede GitHub publication. No scientific case or public release has been accepted yet.

Keep credentials, private originals and runtime workspaces outside Git. Packaged demo material is synthetic. Product investigations are manually triggered, with no default background schedule.

## OA literature collection

## Local RAG (D18, in progress)

```powershell
.venv\Scripts\python -m pip install ".[rag-mcp]"
.venv\Scripts\python -m research_harness.rag --workspace .local\aem-rag status
```

The local RAG reads only the configured catalog, does not read Codex credentials, and does not call a generation model. Its JSON operations are `import`, `search`, `context`, `document`, and `status`. Real-PDF acceptance remains in progress.

`literature` is a separate OpenAlex search and OA-PDF collection module, not RAG or scientific screening. Install its validator, then use the verified 23-item manifest when supplied:

```powershell
.venv\Scripts\python -m pip install ".[literature]"
.venv\Scripts\python -m research_harness.literature search --config examples\aem_oa_reviews.json --output .local\aem-candidates.json
.venv\Scripts\python -m research_harness.literature download --manifest examples\aem_oa_manifest.json --output .local\aem-pdfs --limit 23
```

`anonymous: true` explicitly performs a no-key search; otherwise set `OPENALEX_API_KEY`. The AEM search example uses `review_only: false`: OpenAlex type labels miss reviews, so callers screen records. The downloader verifies readability, identity and optional record-specific `expected_min_pages`; incomplete results return `partial` and exit code 4.
