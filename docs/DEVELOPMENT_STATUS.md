# CirootHarness engineering status

This document is the public source of truth for **implemented and accepted scope**.

Design documents in this repository intentionally describe future architecture as well as completed work. A target design is not evidence that a component is implemented. README claims should link back here or to a specific acceptance record.

## Current integration checkpoint (2026-10-05)

The user approved S0–S6 implementation: [stage contract](INTEGRATION_STAGE.md). Local HEAD is `445cc6c`; the inspected remote is `2b16ef96a74b90ab93445d2a401e2f2051595ea5`. The latest prerelease declares build commit `acf5c62b57a4c4c3d2a412558d6d3eae68a8faca`; it must not be treated as containing all current source changes. Existing local edits are preserved. New work is not accepted merely because its design is listed here.

## Historical and available capabilities

| Area | Status | Evidence / notes |
| --- | --- | --- |
| Public Golden Demo | Accepted deterministic synthetic integration demo | [Golden Demo](GOLDEN_DEMO.md); [tests](../tests/test_golden_demo.py); offline, synthetic, no model API calls, no network required; frozen ResearchSpec; source/query attempts; evidence-bearing documents; verified claims; open normalization issue; technical report and literature review; reopen tested; [CI-covered](../.github/workflows/ci.yml); expected final outcome = `partial`. This is integration acceptance, not scientific, live-source or patent-search acceptance. |
| GUI Golden Demo | Implemented; native desktop acceptance pending | [User guide](GUI_GOLDEN_DEMO.md) and [verification](GUI_GOLDEN_DEMO_ACCEPTANCE.md); localized entry to the canonical offline scenario, real partial/evidence/review/report display, isolated persisted demo data. Browser/API checks passed; native click/run/reopen and published binary availability remain unaccepted. Public screenshot assets are deferred until frontend optimization. |
| D2 fixture framework | Accepted | `docs/FRAMEWORK_ACCEPTANCE.md`; deterministic synthetic sources, LangGraph, SQLite, citation verification and multilingual report outputs |
| D18 local RAG | Implemented with acceptance record | `docs/RAG_ACCEPTANCE.md`; see `docs/RAG_STAGE.md` for the exact boundary |
| OA literature collection | Implemented as a separate collection module | OpenAlex search and OA-PDF collection; collection is not equivalent to scientific screening |
| D19 P1 investigation service | Implemented for accepted offline/host scope | `docs/D19_P1_IMPLEMENTATION.md` and `docs/D19_P1_ACCEPTANCE.md` |
| D19 P3 bounded paper case | Accepted on 2026-09-16 | New-PDF Docling/RAG ingestion, two Chinese report bodies, export and reopen checks; search coverage remained partial |
| Windows desktop preview | Prerelease published on 2026-09-28 | `v0.1.2-desktop-preview`; local workspace/library, PDF/TXT import and local basic text search; packaged-page first-send check passed, native WebView2 interaction unverified |
| D19 P4 patent work | Local bounded live implementation record; independent semantic acceptance pending | `docs/D19_P4_IMPLEMENTATION_REPORT.md`; local `inv-f9883119d113`, partial; 2026-10-05 read-only audit matched 10 artifact hashes and 8 claim identity/quote bindings. This does not establish semantic correctness or wider coverage. |

The desktop prerelease is labeled `v0.1.2-desktop-preview`, while `pyproject.toml` still declares package version `0.1.0`. Release version alignment remains open; this page does not treat the package version as updated.

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
