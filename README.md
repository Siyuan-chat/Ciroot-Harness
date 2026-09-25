# Research Harness

[中文 README 与 Windows GUI 使用说明](README.zh-CN.md) · English · [日本語](README.ja.md)

**2026-09-16 checkpoint:** the bounded P3 paper case passed independent acceptance, including new-PDF Docling/RAG ingestion, two Chinese report bodies, export and reopen checks. Search coverage remains partial. P4 single-family patent work is planned; OPS registration is pending. [P3 acceptance](docs/D19_P3_LOOP2_ACCEPTANCE.md) · [P4 plan](docs/D19_P4_PLAN.md) · [Fallback design](docs/D19_P4_FALLBACK.md).

[Integrated system design (Chinese)](docs/SYSTEM_DESIGN.md) · [Architecture diagram](docs/diagrams/harness-overview.svg) · [D19 experiment plan](docs/INVESTIGATION_EXPERIMENT_PLAN.md). These describe the target design; implementation status is stated separately.

**CirootHarness Windows desktop candidate:** [Chinese quick start and current limits](docs/GUI_QUICKSTART.zh-CN.md). The downloadable package contains no local research corpus, API keys, or model cache; paid research calls require explicit configuration and execution.

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

The first later case is polymer design. [Its draft](examples/polymer-design.draft.json) has unresolved requirements and is not runnable scientific evidence. The bounded P3 paper case is accepted; broader scientific evaluation remains pending. Publishing the desktop candidate does not certify a live research workflow.

Keep credentials, private originals and runtime workspaces outside Git. Packaged demo material is synthetic. Product investigations are manually triggered, with no default background schedule.

## Local RAG (D18)

```powershell
.venv\Scripts\python -m pip install ".[rag-mcp]"
.venv\Scripts\python -m research_harness.rag --workspace .local\aem-rag status
```

The local RAG reads only the configured catalog, does not read Codex credentials, and does not call a generation model. Its CLI operations are `prepare`, `import`, `search`, `context`, `document`, `status`, and `rebuild`; `prepare` only caches parsing, while `rebuild` migrates vectors from existing evidence. See the [local usage guide](docs/RAG_USAGE.en.md), [runtime notes](docs/RAG_RUNTIME.md), [stage boundary](docs/RAG_STAGE.md), and [independent acceptance record](docs/RAG_ACCEPTANCE.md).

## OA literature collection

`literature` is a separate OpenAlex search and OA-PDF collection module, not RAG or scientific screening. Install its validator, then use the verified 23-item manifest when supplied:

```powershell
.venv\Scripts\python -m pip install ".[literature]"
.venv\Scripts\python -m research_harness.literature search --config examples\aem_oa_reviews.json --output .local\aem-candidates.json
.venv\Scripts\python -m research_harness.literature download --manifest examples\aem_oa_manifest.json --output .local\aem-pdfs --limit 23
```

`anonymous: true` explicitly performs a no-key search; otherwise set `OPENALEX_API_KEY`. The AEM search example uses `review_only: false`: OpenAlex type labels miss reviews, so callers screen records. The downloader verifies readability, identity and optional record-specific `expected_min_pages`; incomplete results return `partial` and exit code 4.

## Offline investigation and monitoring (D19 P1)

The investigation service provides eight host-agent roles, source-query accounting, PDF/XML/text evidence, frozen technical reports and literature reviews, and versioned patent monitoring with human-review history. The offline fixture path supports Chinese, English and Japanese outputs.

```powershell
.venv\Scripts\python -m pip install ".[investigation]"
.venv\Scripts\rh investigate --workspace .local\investigation doctor
```

[Host usage](docs/INVESTIGATION_USAGE.en.md) · [Implementation](docs/D19_P1_IMPLEMENTATION.md) · [Independent acceptance and limits](docs/D19_P1_ACCEPTANCE.md). This stage uses explicit synthetic sources and host/replay results; it enables no live model/source API or OS schedule. Existing D18 RAG and OA collection remain separate services.
