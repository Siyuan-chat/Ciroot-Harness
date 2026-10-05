<p align="center">
  <img src="assets/ciroot-harness-logo.png" alt="CirootHarness logo" width="220">
</p>

<h1 align="center">CirootHarness</h1>

<p align="center">
  <strong>Open-source, local-first and auditable AI research for patents and scientific literature.</strong><br>
  Turn a research question into a versioned, evidence-linked, reviewable research record—not just an answer.
</p>

<p align="center">
  <a href="README.zh-CN.md">中文</a> · English · <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <a href="https://github.com/Siyuan-chat/Ciroot-Harness/actions/workflows/ci.yml"><img src="https://github.com/Siyuan-chat/Ciroot-Harness/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0">
  <img src="https://img.shields.io/badge/status-desktop%20preview-orange" alt="Desktop preview">
</p>

<p align="center">
  <a href="https://github.com/Siyuan-chat/Ciroot-Harness/releases">Download Windows preview</a> ·
  <a href="#run-the-offline-demo">Run the offline demo</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="docs/DEVELOPMENT_STATUS.md">Engineering status</a>
</p>

## What is CirootHarness?

CirootHarness is an **open-source research harness for patent research, scientific literature review, local RAG, and evidence-traceable AI-assisted investigation**. It preserves the research specification, source attempts, document versions, evidence locations, review decisions, and execution outcome so that a result can be inspected after the model finishes.

> **Project principle:** `partial` is not `completed`, a citation is not evidence until it can be traced back to the source, and target architecture is not presented as implemented functionality.

> **Current integration status:** S0–S6 integration is proceeding as an offline candidate. See the [integration guide](docs/INTEGRATION_GUIDE.en.md), [current acceptance status](docs/INTEGRATION_STAGE.md) and [activation requirements](docs/INTEGRATION_ACTIVATION.md) for research engines, regional patent sources and deployment. Component tests do not represent real API or scientific acceptance.

## Who is CirootHarness for?

CirootHarness is designed for researchers, R&D teams, patent/research tooling developers, and AI4Science practitioners who need **reproducible, reviewable AI research workflows** rather than answer-only generation. The current public preview is strongest for local literature workflows, deterministic demos, accepted local-RAG paths, and auditable research infrastructure; the live patent workflow is still being integrated and should not be treated as production-ready.

## How is CirootHarness different from a typical research agent?

Typical research agents optimize for a fluent final answer. CirootHarness is being built around a different requirement: **a research result should remain auditable after generation**.

| Concern | CirootHarness approach |
| --- | --- |
| Requirements drift | Versioned `ResearchSpec` with frozen run inputs |
| Untraceable claims | Evidence IDs linked to document versions and locators |
| Citation hallucination | Quote ownership and source-text verification |
| Silent retrieval failures | Explicit `complete` / `partial` / `failed` / `unsupported` states |
| Ambiguous conclusions | Persistent human-review issues and decision history |
| Private corpora | Local-first document storage and RAG path |
| Reproducibility | Frozen inputs, durable artifacts, structured run state |

## What works today

CirootHarness is an active preview, not a finished production research service.

| Capability | Current state |
| --- | --- |
| Windows desktop preview | Portable prerelease for local library workflows; native WebView2 interaction is not fully accepted |
| Local workspace and library | Create workspaces/libraries; import text-extractable PDF and UTF-8 TXT |
| Local basic text search | Available in the desktop preview |
| Offline investigation demo | Deterministic synthetic [Golden Demo](docs/GOLDEN_DEMO.md) using the real InvestigationService; offline, no API key, expected `partial`. |
| Multilingual reports | Chinese, English and Japanese outputs in the fixture workflow |
| Local RAG | Docling/FastEmbed/Qdrant-based workflow with recorded acceptance |
| OA literature collection | OpenAlex search and OA-PDF collection module |
| Investigation service | Evidence, report, review and monitoring primitives are implemented for the accepted offline scope |
| Bounded paper case | P3 case accepted with new-PDF ingestion, RAG, report export and reopen checks |
| Live patent workflow | Still in progress; do not treat the target design as an accepted end-to-end capability |

For the detailed stage-by-stage boundary, see [Engineering status](docs/DEVELOPMENT_STATUS.md).

## Quick start

### 1. Try the Windows desktop preview

Download the current portable ZIP from [GitHub Releases](https://github.com/Siyuan-chat/Ciroot-Harness/releases), extract the **entire** `ResearchHarnessGUI` folder, and run:

```text
ResearchHarnessGUI.exe
```

The window is branded **CirootHarness**. The executable name is currently retained for compatibility.

The preview starts without bundled private documents, model caches, or API keys. The accepted package checks cover workspace and library creation, text-extractable PDF or UTF-8 TXT import, local basic search, and a bounded first-send flow through the packaged page. Native WebView2 interaction remains unverified. See the [Chinese GUI guide](docs/GUI_QUICKSTART.zh-CN.md) for the current boundaries.

<a id="run-the-offline-demo"></a>

### 2. Run the offline demo

**Public Golden Demo**

Python 3.11+ is required. Installation may require network access; execution is offline.

**Windows**

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install ".[investigation]"
.venv\Scripts\rh investigate --workspace .local/golden-demo golden-demo
```

**macOS / Linux**

```bash
python -m venv .venv
.venv/bin/python -m pip install ".[investigation]"
.venv/bin/rh investigate --workspace .local/golden-demo golden-demo
```

Runs the deterministic synthetic Golden Demo through the real InvestigationService. No model API key or network access is required.

The Golden Demo intentionally contains one malformed synthetic XML document, so the expected outcome is `partial`, not `completed`.

It freezes a ResearchSpec, records source/query attempts, produces evidence-backed verified claims and an open normalization issue, and exports a technical report and a literature review. See the [Golden Demo guide](docs/GOLDEN_DEMO.md) for persisted results and reopening.

The older `rh demo` remains a legacy framework fixture demo; see the [user guide](docs/USER_GUIDE.en.md).

This synthetic integration demo is separate from real scientific evidence and live-source acceptance.

## Architecture

The diagram below is the public architecture overview. Detailed engineering design and stage-specific acceptance remain in the linked technical documents.

The target system takes a research question through specification, retrieval, evidence extraction, verification, human review, and report generation.

![CirootHarness architecture](docs/diagrams/cirootharness-architecture.en.png)

[Full-size PNG](docs/diagrams/cirootharness-architecture.en.png) · [editable SVG](docs/diagrams/cirootharness-architecture.en.svg)

The diagram describes the integrated design. **Implemented/accepted scope is tracked separately** so that planned components are not confused with working product behavior.

Read the [integrated system design](docs/SYSTEM_DESIGN.md), [architecture notes](docs/ARCHITECTURE.md), and [engineering status](docs/DEVELOPMENT_STATUS.md).

## Local RAG

Install the RAG/MCP extras:

```powershell
.venv\Scripts\python -m pip install ".[rag-mcp]"
.venv\Scripts\python -m research_harness.rag --workspace .local\aem-rag status
```

The local RAG reads only the configured catalog. It does not read Codex credentials and does not invoke a generation model by itself.

See [RAG usage](docs/RAG_USAGE.en.md), [runtime notes](docs/RAG_RUNTIME.md), [stage boundary](docs/RAG_STAGE.md), and [acceptance record](docs/RAG_ACCEPTANCE.md).

## OA literature collection

The `literature` module performs OpenAlex search and OA-PDF collection. It is intentionally separate from scientific screening and RAG.

```powershell
.venv\Scripts\python -m pip install ".[literature]"
.venv\Scripts\python -m research_harness.literature search --config examples\aem_oa_reviews.json --output .local\aem-candidates.json
.venv\Scripts\python -m research_harness.literature download --manifest examples\aem_oa_manifest.json --output .local\aem-pdfs --limit 23
```

## Investigation service

The investigation layer contains host-agent roles, source-query accounting, evidence records, frozen reports, review history, and patent-monitoring primitives.

```powershell
.venv\Scripts\python -m pip install ".[investigation]"
.venv\Scripts\rh investigate --workspace .local\investigation doctor
```

See [investigation usage](docs/INVESTIGATION_USAGE.en.md), [implementation record](docs/D19_P1_IMPLEMENTATION.md), and [accepted scope](docs/D19_P1_ACCEPTANCE.md).

## Demo and showcase

The public demo should prove four things quickly:

1. a question becomes a frozen research specification;
2. the system records what it searched and what actually succeeded;
3. claims can be opened back to evidence and source locations;
4. the final report distinguishes verified conclusions from unresolved review items.

The capture plan, screenshot naming convention, 60–90 second demo storyboard, and truthfulness rules live in [Demo showcase guide](docs/DEMO_SHOWCASE.md).

## Current boundaries

The current public preview should **not** be interpreted as all of the following being production-ready:

- live model + live source API end-to-end investigation;
- complete patent-family search coverage;
- OCR for scanned PDFs;
- cross-library semantic search in the desktop preview;
- unattended production monitoring;
- a legal opinion, freedom-to-operate opinion, or patentability determination.

Credentials, private originals, runtime workspaces, and model caches should stay outside Git.

## Documentation

- [Golden Demo](docs/GOLDEN_DEMO.md)
- [Engineering status](docs/DEVELOPMENT_STATUS.md)
- [System design](docs/SYSTEM_DESIGN.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Product requirements](docs/PRD.md)
- [Data and adapter contracts](docs/CONTRACTS.md)
- [Framework acceptance](docs/FRAMEWORK_ACCEPTANCE.md)
- [RAG acceptance](docs/RAG_ACCEPTANCE.md)
- [Investigation plan](docs/INVESTIGATION_EXPERIMENT_PLAN.md)
- [User guide](docs/USER_GUIDE.en.md)

## Citation

If CirootHarness is useful in academic or technical work, please cite the repository using [`CITATION.cff`](CITATION.cff).

## License

Licensed under the [Apache License 2.0](LICENSE).
