# Research Harness implementation report — Alpha 0.1.0

## D2 fixture-framework checkpoint (2026-09-09)

- `cb7cbc0`: `python -m research_harness.cli demo --workspace .local\demo-k01` completed the synthetic fixture workflow through all seven stages, retained the review issue, and wrote the report artifacts.
- `2a8cf5d`: the fixture specification and baseline text were added to package resources; the bundled-resource checks and source-tree compile check passed.
- Final clean-wheel installation and independent K01–K07 acceptance remain pending the design task.

Date: 2026-09-09. This is an implementation self-test record, not independent acceptance and not a scientific-case result.

## Delivered scope

- Source package: `src/research_harness`; CLI entry point: `rh`.
- Dependency-free public-contract validation for `ResearchSpec` and `RuntimeConfig`.
- SQLite-backed versioned specifications, immutable SHA-256 raw-file storage, document-role separation, run manifests and review-decision history.
- Local-only doctor, manual preflight, frozen baseline IDs, execution-mode labels, immutable JSON/Markdown/HTML snapshots and formula-safe CSV export.
- Offline fixture execution is explicitly labelled `local_fixture`/`synthetic`; enabled external sources are reported pending rather than as an empty successful search.

## Verification performed

```powershell
$env:PYTHONPATH='src'
& 'C:\Users\Siyuan_ye\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
& 'C:\Users\Siyuan_ye\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m research_harness.cli --help
& 'C:\Users\Siyuan_ye\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m research_harness.cli validate --spec examples\polymer-design.draft.json
```

Result: six fixture tests passed: draft preflight rejection, immutable import + baseline freeze + multilingual report export, full Schema regression counterexamples, frozen report snapshots, and offline doctor. `compileall` and `git diff --check` passed. A non-editable wheel was built and installed in an isolated project venv; `rh --help` ran from that installed wheel and confirmed the bundled public Schema resource.

XML/text ingestion now persists `parsed`/`failed` status and parse errors in SQLite. Supported XML paragraph-like nodes retain mixed inline text and stable IDs; unsupported XML structures and PDF page/bounding-box provenance remain pending Docling integration.

`pip install -e . --no-deps` built the editable wheel with `--no-build-isolation`; installation then failed because this managed interpreter cannot write its user site-packages. This is an environment-permission limitation, not an installation-success claim. A normal developer Python environment should use `python -m pip install --no-build-isolation -e .`; this remains pending independent environment verification.

## Dependency and model record

Core runtime uses Python 3.11+ standard library. The validated fixture model ID is `fixture-local`, a test marker rather than a real model. Optional production extras declared in `pyproject.toml` are LangGraph, Docling, FastEmbed, Qdrant client and LlamaIndex core. They were not installed or exercised in this offline environment; no FastEmbed model ID/license can be claimed yet.

## Acceptance status

| IDs | Status | Evidence / gap |
|---|---|---|
| A01, A03, A04 | partially implemented, fixture-tested | CLI validation/preflight and SQLite version conflict exist; installed-wheel smoke test passed. |
| A05 | partially implemented | Runtime is validated by the public Schema and preflight requires configured credentials; real OpenAI-compatible/Anthropic adapters pending. |
| A07, A08, A16, A23, A25, A30 | partially implemented, fixture-tested | Raw files, exact frozen baseline IDs, immutable ReportData, partial source representation, canonical outputs and CSV formula protection exist. |
| A02, A06, A09–A15, A17–A22, A24, A26–A29, A31–A34 | pending | Intake/chat, Docling/XML evidence extraction, FastEmbed/Qdrant/LlamaIndex retrieval, LangGraph checkpointing, OpenAlex/EPO adapters, analysis/verification, issue creation/reopen, locking and full report semantics are not implemented. |
| G3, G4 | pending / out of scope | No credentials, real case material, public demo or release. |

## Artifacts and limits

Runtime data stay under the user-supplied workspace: `raw/`, `research.sqlite`, and `reports/<run-id>/`. The tests use temporary directories and leave no case data in the repository.

Important limit: this alpha is a conservative local foundation, not the complete M1–M5 Research Harness described in the handoff. It must not be represented as a completed investigation engine. The next implementation tranche is intake/chat plus production parser/retrieval/source integrations, followed by local-component and bounded online acceptance tests.
