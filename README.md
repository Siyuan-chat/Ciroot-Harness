# Research Harness

[中文](README.zh-CN.md) · English · [日本語](README.ja.md)

A local-first literature and patent investigation harness. Describe a research need in natural language; an LLM clarifies consequential ambiguities and produces a versioned JSON specification. A manually triggered investigation retrieves documents, compares cited evidence with a frozen local reference library, and produces reports plus a persistent human-review queue.

**Current status: implemented alpha, pending independent acceptance.** The local CLI, versioned specification store, SQLite document store, offline fixture workflow and report renderer are implemented. Optional production integrations (LangGraph, Docling, FastEmbed/Qdrant/LlamaIndex, OpenAlex/EPO and model APIs) require their documented extras, configuration and independent acceptance. No real polymer-design case evaluation or publishable demo has been performed.

## Agreed behavior

- Chinese, English and Japanese conversation, retrieval, reports and review lists.
- Manual updates on a local computer; no background scheduler in v1.
- Local originals, local indexes and local embeddings; relevant evidence excerpts may be sent to the configured model API.
- Separate model API and data-source credentials. Supported providers are configured without changing source code.
- Missing or conflicting evidence becomes a watch item and a human-review issue; the investigation continues.
- Human decisions apply to individual findings. Global criteria change only when explicitly requested.
- Reports preserve document identity, source locations, test conditions, baseline and specification versions.

## Design package

| Document | Purpose |
|---|---|
| [Product requirements](docs/PRD.md) | Scope, requirement IDs and default behavior |
| [Architecture](docs/ARCHITECTURE.md) | Components, workflow, persistence and provider boundaries |
| [Data contracts](docs/CONTRACTS.md) | Executable JSON, evidence, findings and review semantics |
| [Acceptance plan](docs/ACCEPTANCE.md) | Framework, integration, case and release gates |
| [Terra handoff](docs/HANDOFF_TERRA.md) | Implementation order and required delivery |
| [Decision register](docs/DECISIONS.md) | Accepted decisions, defaults and remaining case inputs |
| [English guide](docs/USER_GUIDE.en.md) | Intended user journey and CLI contract |

[Research specification schema](schemas/research-spec.schema.json) · [Runtime schema](schemas/runtime.schema.json) · [Polymer-design draft](examples/polymer-design.draft.json)

The first case is **polymer design**. The domain belongs in a research specification; it must not be hard-coded into the harness. The draft contains no measured values, named target polymer or scientific conclusions.

Install from source with `python -m pip install --no-build-isolation -e .`, then run `rh --help`. The `--no-build-isolation` switch is useful in offline environments with a preinstalled build backend. See `docs/IMPLEMENTATION_REPORT.md` for tested commands and evidence boundaries.

The target is a GitHub open-source release with a reproducible demo after acceptance. Repository identity, final license and demo redistribution rights are resolved before publication; no publication has occurred.
