---
title: CirootHarness — Auditable AI research for patents and scientific literature
description: CirootHarness is an open-source, local-first research harness for evidence-traceable patent and scientific-literature workflows.
---

# CirootHarness

**CirootHarness is an open-source, local-first and auditable AI research harness for patent research and scientific literature.** It is built around evidence traceability, reproducibility, explicit coverage states, and human review.

Instead of treating the final answer as the only artifact, CirootHarness keeps the research specification, source attempts, document versions, evidence locators, review decisions, and execution outcome so a result can be inspected after generation.

[View the source on GitHub](https://github.com/Siyuan-chat/Ciroot-Harness){ .md-button .md-button--primary }
[Try the current release](https://github.com/Siyuan-chat/Ciroot-Harness/releases){ .md-button }

## Why a research harness?

Many research agents are optimized to produce fluent prose. CirootHarness is designed around a different requirement: **a research result should remain reviewable after the model finishes**.

| Research problem | CirootHarness approach |
| --- | --- |
| Requirements drift | Versioned `ResearchSpec` and frozen run inputs |
| Claims without inspectable support | Evidence IDs linked to document versions and locators |
| Citation hallucination | Quote ownership and source-text verification |
| Hidden retrieval failure | Explicit `complete` / `partial` / `failed` / `unsupported` states |
| Ambiguous conclusions | Persistent review issues and decision history |
| Private corpora | Local-first document storage and RAG paths |
| Reproducibility | Durable artifacts and structured run state |

## What can I use today?

The public repository currently provides an accepted deterministic Golden Demo, local workspace/library flows, accepted local-RAG paths, OA literature collection components, investigation/report/review primitives, and a Windows desktop preview.

The project is still an active preview. **Live patent research is being integrated and must not be interpreted as complete production coverage or as a legal opinion service.**

See [Current status](current-status.md) for the public capability boundary.

## Who is it for?

CirootHarness is aimed at researchers, R&D teams, research-tool developers, patent-research tooling developers, and AI4Science practitioners who need inspectable and reproducible AI-assisted research workflows.

## Start here

- [Getting started](getting-started.md)
- [Current status and limitations](current-status.md)
- [Golden Demo](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/GOLDEN_DEMO.md)
- [System design](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/SYSTEM_DESIGN.md)
- [Architecture](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/ARCHITECTURE.md)

## Other languages

The repository README is also available in [简体中文](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/README.zh-CN.md) and [日本語](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/README.ja.md).
