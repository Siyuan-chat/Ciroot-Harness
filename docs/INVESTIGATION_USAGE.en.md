# Offline investigation host

Install the project's investigation dependencies, then call the local
`InvestigationService` through `rh investigate ...`:

```powershell
rh investigate --workspace .local/d19-workspace doctor
rh investigate --workspace .local/d19-workspace start --spec .\examples\investigation\synthetic-spec.json --runtime .\examples\investigation\synthetic-runtime.json --scenario .\examples\investigation\synthetic-scenario.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
```

The MCP entry point is `python -m research_harness.investigation_mcp
--workspace PATH`. P1 supports offline host mode with explicit synthetic/replay
inputs only. It does not call live sources, generation APIs, or OS schedulers.
Submit the exact task version and preserve missing values, uncertainty, exact
source quotes, and locators. Initial local work can block this single process;
do not run CLI writes while the same library is open in MCP.
Monitor configuration can be validated without execution, then inspected:

```powershell
rh monitor --workspace .local/d19-workspace validate --profile profile.json --spec monitor.json --runtime runtime.json
rh monitor --workspace .local/d19-workspace status MONITOR_ID
rh monitor --workspace .local/d19-workspace create --profile profile.json --spec monitor.json --runtime runtime.json --scenario .\examples\investigation\synthetic-scenario.json
```
A complete offline investigation flow is: install the project (for example, `pip install -e .[investigation]`), prepare the spec/runtime/scenario JSON files under `examples/investigation`, then:

```powershell
rh investigate --workspace .local/d19-workspace start --spec .\examples\investigation\synthetic-spec.json --runtime .\examples\investigation\synthetic-runtime.json --scenario .\examples\investigation\synthetic-scenario.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
rh investigate --workspace .local/d19-workspace submit RUN_ID TASK_ID --result result.json --task-version 1
rh investigate --workspace .local/d19-workspace work RUN_ID
rh investigate --workspace .local/d19-workspace resume RUN_ID
rh investigate --workspace .local/d19-workspace report RUN_ID
```

Inputs are user supplied offline JSON and explicit synthetic scenarios. The adapter does not call live sources or generation APIs. For monitoring, use `run-once`, then `review` and explicit `decide`:

```powershell
rh monitor --workspace .local/d19-workspace run-once MONITOR_ID --scenario .\examples\investigation\synthetic-scenario.json
rh monitor --workspace .local/d19-workspace review --monitor-id MONITOR_ID
rh monitor --workspace .local/d19-workspace decide ISSUE_ID --decision relevant --note note
```
## Monitor fields and deterministic replay

`profile.json` must include `company_id`, `rule_version`, and `scope`; a monitor spec must include `name` and `report_languages`. Every synthetic cycle scenario must explicitly provide `cycle_key`, `window_start`, and `window_end`; the host never infers the window from the system clock. Update a profile with:

```powershell
./scripts/investigation.ps1 -Monitor -Command profile-update -Workspace .local/d19-workspace -RunId MONITOR_ID -Profile profile-v2.json
```

The adapter calls the application service only. It does not install an OS watcher or scheduler and does not access live APIs. `scripts/investigation_replay.py` consumes JSON saved from `get_pending_tasks` and emits deterministic zh/en/ja structured results marked `synthetic=true`; this is a test/replay driver, not real model reasoning or scientific evidence:

```powershell
python scripts/investigation_replay.py --pending pending.json --output replay-result.json
```

An installed package does not require `PYTHONPATH`. First install with the same interpreter used by PowerShell: `python -m pip install .[investigation]`, then run the commands below; set `PYTHONPATH=<worktree>\src` only for source-tree development checks.

## Opt-in live OpenAlex (P2)

Set `data_mode` to `live`, set `allow_network` to `true`, and configure only
`sources.openalex`. Choose `anonymous: true`, or an `api_key_env` name; never
put a key in JSON. The scenario must provide auditable, already-retrieved
`reference_evidence`; live collection never imports the local RAG library.
Search and download attempts, cursors, byte/count limits, full-text gaps, and
the `synthetic: false` result flag are exposed through this same service, CLI,
and MCP. Downloaded originals stay under the investigation workspace.

### Discovery-library RAG fact attachment (P3)

After live acquisition and while `evidence_analysis/extract` is pending, a host
may call `InvestigationService.attach_discovery_evidence(run_id, evidence,
mappings, bibliography=None)`. Each RAG evidence item retains its
`evidence_id`, `document_id`, `version_id`, original `text`, and `locator`; its
mapping binds it to the acquired OpenAlex document/version, DOI, and downloaded
SHA256. The smallest input shape is:

```json
{"evidence":[{"evidence_id":"ev-rag","document_id":"doc-rag","version_id":"ver-rag","text":"original excerpt","locator":{"page":1}}],"mappings":[{"investigation_document_id":"W123","investigation_version_id":"openalex-oa-pdf","doi":"10.1234/example","sha256":"downloaded-content-hash","rag_document_id":"doc-rag","rag_version_id":"ver-rag"}]}
```

An attachment may update pending tasks and increments their `task_version`; a
host that already fetched a task must call `get_pending_tasks` again before
submitting. The identical attachment returns `reused` without an increment.
Facts cannot change after analysis or business-judgment submission. This call
does not download, parse, or modify the RAG index.

