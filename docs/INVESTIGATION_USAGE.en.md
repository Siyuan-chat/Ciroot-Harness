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

In PowerShell, first set the source path: `$env:PYTHONPATH='C:\path\to\terra\src'`.

Install the lightweight host extras with `pip install -e .[investigation]`.

