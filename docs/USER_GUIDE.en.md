# User guide: D2 fixture framework

D2 validates the offline framework and extension interfaces. Real APIs, production RAG, PDF/OCR, standalone chat and GUI are not integrated; optional dependencies do not enable them. The host assistant clarifies requirements and supplies ResearchSpec JSON. Product runs are manually triggered.

## Install and run

Python 3.11+; run in a source checkout on Windows:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .
.venv\Scripts\rh demo --workspace .local\demo
.venv\Scripts\rh status --workspace .local\demo
```

Dependency installation needs network access or prepared package caches. The demo needs neither network access nor keys. A built wheel can be installed with `.venv\Scripts\python -m pip install path\research_harness-0.1.0-py3-none-any.whl`. Keep the demo workspace separate from real materials. On macOS/Linux, executable paths use `.venv/bin/`; independent runtime acceptance currently targets Windows.

The packaged ready spec uses project `fixture-demo`, two synthetic candidates and one synthetic reference. The command returns `run_id/outcome/stage/error/artifacts.report`. The report directory contains three language-specific HTML files, three Markdown files, `report.json` and `review.csv`. One default candidate creates a review issue.

## Custom synthetic input

Save this as `prepare_fixture.py` and run it to copy installed examples:

```python
from importlib.resources import files
from pathlib import Path
base = files('research_harness').joinpath('fixtures')
for source, target in [('demo-spec.json', 'research.json'), ('demo.json', 'candidates.json')]:
    Path(target).write_text(base.joinpath(source).read_text(encoding='utf-8'), encoding='utf-8')
```

Edit the topic, objectives or budget, then run:

```powershell
.venv\Scripts\rh validate --spec research.json
.venv\Scripts\rh demo --workspace .local\custom --spec research.json --fixture candidates.json
```

Validation does not start a run. Execution requires `status=ready` and `unresolved_questions=[]`. Edited content at an existing project/revision receives a new revision; repeated identical content reuses the saved version. Input files are not rewritten. Old configurations, reference snapshots and reports stay frozen.

Fixture shape: `{"candidates":[{"id":"synthetic-1","quote":"Synthetic text.","locator":"line:1"}]}`. IDs must be unique and quotes nonempty; optional `missing:true` demonstrates missing support. These are test inputs, not search results or scientific claims. With `--spec`, the default reference is not automatically imported. To select a simple local text reference:

```powershell
.venv\Scripts\rh import baseline.txt --workspace .local\custom --collection baseline --kind paper
```

Use `reference_library.collection_ids/document_ids` to select references. Discoveries are not automatically promoted. The polymer-design example remains a draft for later case preparation.

## Review and export

Replace `RUN_ID` and `ISSUE_ID` with IDs returned by your run:

```powershell
.venv\Scripts\rh review list --workspace .local\demo
.venv\Scripts\rh review decide ISSUE_ID --decision watch --note "Keep pending further evidence" --workspace .local\demo
.venv\Scripts\rh report RUN_ID --workspace .local\demo --languages zh,en,ja
```

include/exclude/watch saves a per-item decision and resolves the issue; request_more_evidence keeps it open. Decisions do not change global criteria or frozen reports. Re-exporting an old run uses its original snapshot; review list shows current decisions.

## Python and future GUI boundary

```python
from research_harness.service import Harness
from research_harness.errors import HarnessError
h = Harness('.local/custom')
try:
    result = h.run_fixture('research.json', 'candidates.json', on_progress=lambda e: print(e))
    print(h.status())
    print(h.get_result(result['run_id']))
    print(h.get_artifacts(result['run_id']))
except HarnessError as exc:
    print(exc.to_dict())
finally:
    h.close()
```

The service itself does not print. Progress events contain run_id/stage/status. get_result returns decoded frozen facts; get_artifacts returns `{report,files}` with language/format/path per file; review_decide returns the updated issue. Clients need no SQLite access or CLI-output parsing.

Inject `source_adapter(candidates)` or `model_adapter(spec,candidate,candidate_evidence,reference_evidence)`. Model output uses ordinary JSON fields disposition/comparison_result/rationale and candidate/reference citations `{evidence_id,quote}`. The harness verifies ownership and exact text. See [contracts](CONTRACTS.md). Real provider integration still requires implementing its adapter.

## Outcomes and limits

Demo exit codes: completed=0, partial=4, failed=3, invalid input=2. Exceeding max_candidates saves partial results. Source and export failures remain explicit. Stable codes include RH_INVALID_INPUT, RH_PRECONDITION, RH_NOT_FOUND, RH_EXPORT_FAILED and RH_UNSUPPORTED; public errors exclude raw external exceptions.

D2 covers representative budget/failure paths, not crash recovery or every budget dimension. chat/live are unsupported; lexical_test_only is a legacy test path. Keep originals, credentials, SQLite and reports in ignored workspaces. Real API/library integration, polymer case acceptance and GitHub publication follow this framework phase.
