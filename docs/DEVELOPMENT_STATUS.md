# CirootHarness engineering status

This document is the public source of truth for **implemented and accepted scope**.

Design documents in this repository intentionally describe future architecture as well as completed work. A target design is not evidence that a component is implemented. README claims should link back here or to a specific acceptance record.

## Current public checkpoint

| Area | Status | Evidence / notes |
| --- | --- | --- |
| D2 fixture framework | Accepted | `docs/FRAMEWORK_ACCEPTANCE.md`; deterministic synthetic sources, LangGraph, SQLite, citation verification and multilingual report outputs |
| D18 local RAG | Implemented with acceptance record | `docs/RAG_ACCEPTANCE.md`; see `docs/RAG_STAGE.md` for the exact boundary |
| OA literature collection | Implemented as a separate collection module | OpenAlex search and OA-PDF collection; collection is not equivalent to scientific screening |
| D19 P1 investigation service | Implemented for accepted offline/host scope | `docs/D19_P1_IMPLEMENTATION.md` and `docs/D19_P1_ACCEPTANCE.md` |
| D19 P3 bounded paper case | Accepted on 2026-09-16 | New-PDF Docling/RAG ingestion, two Chinese report bodies, export and reopen checks; search coverage remained partial |
| Windows desktop preview | Prerelease published on 2026-09-28 | `v0.1.1-desktop-preview`; local workspace/library, PDF/TXT import and local basic text search; packaged-page first-send check passed, native WebView2 interaction unverified |
| D19 P4 patent work | Planned / in progress | Single-family patent stage designed; OPS registration was pending at the recorded checkpoint |

The desktop prerelease is labeled `v0.1.1-desktop-preview`, while `pyproject.toml` still declares package version `0.1.0`. Release version alignment remains open; this page does not treat the package version as updated.

## Available and demonstrable

The public repository can currently demonstrate:

- validated and revisioned research specifications;
- frozen run inputs;
- local original/evidence storage;
- reference/discovery separation;
- deterministic fixture source/model callables;
- LangGraph orchestration in the fixture framework;
- SQLite persistence;
- citation ownership / quote checks;
- persistent review decisions;
- explicit partial/failed outcomes;
- local RAG tooling;
- OA literature collection;
- investigation/report/review service primitives;
- multilingual outputs in accepted fixture workflows;
- a Windows desktop preview for local library workflows, with packaged-page checks and an open native WebView2 acceptance boundary.

## Do not overclaim

Until a newer acceptance record explicitly says otherwise, the project should not claim production-ready support for:

- complete live model + live source API end-to-end investigation;
- complete EPO/patent-family coverage;
- OCR of scanned PDFs;
- desktop cross-library semantic search;
- unattended production monitoring;
- legal opinions such as FTO, infringement, validity, or patentability conclusions.

## How to update this file

When a stage changes:

1. link the immutable acceptance or validation record;
2. state the actual data mode used: synthetic, replay, bounded live, or live;
3. record whether coverage was complete, partial, failed, or unsupported;
4. separate UI availability from backend capability;
5. avoid replacing a scoped acceptance statement with a broader marketing claim.

Historical implementation details remain in the stage-specific documents.
