---
title: AI-assisted patent research with verifiable evidence
description: AI-assisted patent research should preserve queries, source attempts, patent-document identities, evidence locations, uncertainty, and review boundaries.
---

# AI-assisted patent research with verifiable evidence

**AI-assisted patent research with verifiable evidence** uses models to help plan, retrieve, organize, compare, or explain patent material while keeping enough source state for a human to inspect how a conclusion was formed.

For a reviewable workflow, the important output is not simply a paragraph with patent numbers. The system should preserve the search expression or retrieval intent, source attempt, patent-document identity, document version or publication record, evidence location, and any unresolved review issue.

## What should a verifiable patent-research workflow record?

At minimum:

1. **Research scope** — the technical question and constraints being investigated.
2. **Queries and source attempts** — what was actually sent to which source.
3. **Candidate identity** — publication number and other stable metadata where available.
4. **Source text and version** — the material actually analyzed.
5. **Evidence locator** — claims, description, examples, or other source location.
6. **Interpretation state** — what the system inferred and what remains uncertain.
7. **Coverage state** — whether retrieval was complete, partial, failed, or unsupported.
8. **Human review** — issues that require technical or legal judgment.

## What CirootHarness is building

CirootHarness's architecture is designed to combine patent and scientific-literature investigation around a shared evidence and review model. It records research specifications, source attempts, evidence identities, review history, and report state.

However, the current public project **does not claim complete live patent-family coverage or production-ready end-to-end patent research**. Live patent integration remains an active integration area and its accepted scope is narrower than the target architecture.

See [Current status](../current-status.md) before treating a design document as an implemented capability.

## Patent research is not a legal opinion

Technical search, retrieval, evidence organization, and comparison can support a patent professional or R&D team, but they do not automatically establish infringement, validity, freedom to operate, or patentability.

CirootHarness therefore keeps legal-opinion claims outside the current public capability boundary.

## Why combine patents and scientific literature?

Technical questions often span both publication systems. A shared harness can make the evidence model consistent while still keeping source-specific identities, query syntax, coverage limitations, and document semantics separate.

The value is not to pretend that papers and patents are interchangeable. It is to give both source classes a common auditable research envelope.

---

**Last verified:** 2026-10-05  
**Public preview reference:** v0.1.2-desktop-preview  
**Engineering boundary:** [DEVELOPMENT_STATUS.md](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/DEVELOPMENT_STATUS.md)
