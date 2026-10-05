# Research engines and regional patent sources

This delivery proceeds as an offline candidate. See [stage status](INTEGRATION_STAGE.md) and [activation requirements](INTEGRATION_ACTIVATION.md). Installation, component tests and acceptance of real research are separate records.

Freeze the question, document scope, source permissions, model profile and numerical budget before starting. Bind document versions and parse revisions. Re-parsing creates a new revision; historical reports retain their original bindings. Label public, synthetic and company material explicitly.

PaperQA2 and STORM produce drafts and candidate claims. Each citation must resolve uniquely to an internal document, version, parse revision and original location. Missing or ambiguous bindings require review. An exact quotation does not prove semantic support; interpretation and rewriting require their own acceptance.

Keep the desktop EXE separate from optional engine environments. Run `packaging/install_research_env.ps1` with absolute paths to the base Python, core wheel, core lock and engine lock. Conflicting locks stop installation before the environment is created. The installation record includes wheel and lock hashes.

Copy `research_engine.python_executable` from the generated configuration into the complete run configuration, then provide the selected engine's model, embedding and cache settings. The installation record is not a complete run configuration. Runtime does not install dependencies; use capability diagnostics for missing requirements.

Use PowerShell 7.0 or later; these installation and build scripts do not support Windows PowerShell 5.1. From the delivery bundle root, use this PowerShell example after replacing the base Python path with an installed local CPython 3.12. Choose your own environment and installation-record paths. Installation retrieves pinned public dependencies and does not start research.

```powershell
$basePython = 'C:\replace\Python312\python.exe'
$bundle = (Get-Location).Path
$runtime = Join-Path $bundle 'optional-runtime'
& (Join-Path $runtime 'install_research_env.ps1') -Profile paperqa -BasePython $basePython -CoreWheel (Join-Path $runtime 'wheels\research_harness-0.1.0-py3-none-any.whl') -CoreLockFile (Join-Path $runtime 'requirements\core-lock.txt') -LockFile (Join-Path $runtime 'requirements\paperqa-runtime.txt') -EnvironmentPath (Join-Path $bundle 'research-envs\paperqa') -ConfigPath (Join-Path $bundle 'research-envs\paperqa.installation.json')
```

STORM requires a separate environment, configuration path and its own lock. Do not install it into the PaperQA environment.

Use named environment variables for credentials. Never put secrets in documents, run JSON, reports or the repository. Real research needs a new run and an explicit budget. Model calls, embeddings and source requests share the run allowance. Calls with unknown outcomes retain their reservation and are not automatically resent.

Number lookup, keyword search, case enrichment, file download and terminology lookup declare separate capabilities. Enabling a source does not enable every operation. See the [source matrix](SOURCE_API_MATRIX.md). Missing credentials, missing specifications, failures and successful empty results have distinct states.

Review the original location and continuous quotation, then assess support under comparable conditions. Rejected blocks retain drafts and diagnostics. Export, close and reopen to verify historical reports, reviews, receipts and budgets. Replay uses saved inputs without searching again.

Windows uses the lightweight EXE with optional engine environments. The service starts through `python -m research_harness.gui` and binds to `127.0.0.1` by default. Other bind addresses require explicit `--host` and exact `--allowed-hosts`. Initial self-hosting supports one user or a trusted network.

Docker has core, optional research and isolated Demo configurations with persistent workspace/library volumes. Image rebuild and recovery require a real Docker host test. The public Demo uses synthetic or explicitly permitted frozen material; its server rejects real models, fetching, uploads and administrative writes. This delivery provides deployment configuration without public publication.

Use the [evaluation protocol](INTEGRATION_EVALUATION.md) for scientific comparisons. Unannotated claims remain unassessed; do not infer cost or quality improvements.

Patent structure uses `rh patent-analyze --input "C:\path\to\AEM\examples\patent_analysis\frozen-input.synthetic.json"`. Replace this with a real absolute local path. The example is synthetic. Algorithm pins are in `requirements/patent-analysis-lock.txt`; missing dependencies produce partial results and diagnostics, with exit code 4. Analysis does not accept claims or write the investigation database.

From the full source root, with the core package installed, run the offline protocol example:

```sh
python scripts/evaluate_integration.py --case examples/integration_evaluation/case.json --results-dir examples/integration_evaluation --annotations examples/integration_evaluation/annotations-template.json --output evaluation-offline.json
```

This checks the protocol and pending activation states. It is not a real three-engine comparison. Keep real annotations in a separate file and replace `--annotations`; preserve the frozen examples.

## Source execution

Source diagnostics use `rh patent-source-diagnose --workspace "C:\path\to\investigation" --run-id RUN_ID`. Explicit execution currently uses the CLI; the GUI and HTTP API do not yet expose a source execution action. The workspace must contain the investigation's `investigation.sqlite`.

```powershell
rh patent-source-execute --workspace "C:\path\to\investigation" --run-id RUN_ID --task-id TASK_ID --task-version 1 --request-id NEW_REQUEST_ID --source jpo --operation app_progress --params-file "C:\path\to\jpo-params.json" --input-refs-file "C:\path\to\frozen-task-refs.json"
```

Replace the IDs and task version. Read the current task through `GET /api/v1/runs/{run_id}/tasks` or `InvestigationService.get_pending_tasks`; save its exact `input_refs` array in the references file. Parameters are a local UTF-8 JSON object; JPO `app_progress` requires a valid `application_number`. Credentials remain in the configured environment variables. New runs default to zero source-call budget. Raw responses remain drafts awaiting parsing, not accepted evidence. Exit codes are 0 for complete/no match, 4 for pending activation/partial results, and 2 for invalid input. Do not retry an unknown outcome under a different request ID.

## Docker

Docker requires the complete source root as its build context and an available Docker host:

```sh
docker compose --env-file compose.env.example up --build research
docker compose --env-file compose.env.example --profile demo up --build demo
docker compose --env-file compose.env.example --profile paperqa up --build research_paperqa
docker compose --env-file compose.env.example --profile storm up --build research_storm
```

Ports bind to the local host by default. Configure explicit hostnames through `RH_ALLOWED_HOSTS`. Preserve workspace/library volumes; do not use `down -v` for rebuilds. Dockerfiles and Compose files alone are not a complete build context. These images have not been built or run on this host.
