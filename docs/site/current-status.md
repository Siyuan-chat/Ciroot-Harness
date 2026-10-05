---
title: CirootHarness current status and limitations
description: Public capability boundary for the CirootHarness research harness.
---

# Current status and limitations

CirootHarness is an active public preview, not a finished production research service.

The authoritative engineering source of truth is the repository's [DEVELOPMENT_STATUS.md](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/DEVELOPMENT_STATUS.md). This page provides the public discovery-oriented summary.

## Demonstrable today

The repository can currently demonstrate:

- versioned and validated research specifications;
- frozen run inputs;
- durable document/evidence storage;
- explicit source attempts and coverage state;
- evidence-linked claims and quote/source checks;
- persistent review decisions;
- local RAG tooling with recorded acceptance;
- OpenAlex-based OA literature collection;
- investigation, report, review and monitoring primitives in their accepted scope;
- multilingual outputs in accepted fixture workflows;
- a deterministic offline Golden Demo;
- a Windows desktop preview for local library workflows.

## Do not overclaim

Until a newer acceptance record says otherwise, CirootHarness should not claim production-ready support for:

- complete live model + live source API end-to-end investigation;
- complete EPO or patent-family coverage;
- OCR of scanned PDFs;
- desktop cross-library semantic search;
- unattended production monitoring;
- legal opinions such as freedom-to-operate, infringement, validity, or patentability conclusions.

## How status is represented

CirootHarness intentionally distinguishes `complete`, `partial`, `failed`, and `unsupported` outcomes. A source failure or evidence gap should remain visible in the persisted research state and public report.

This status discipline is part of the product design, not an error message to hide.
