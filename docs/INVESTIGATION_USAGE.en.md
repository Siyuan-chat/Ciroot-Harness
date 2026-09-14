# Offline investigation host

Install the project's investigation dependencies, then call the local
`InvestigationService` through `rh investigate ...`:

```powershell
rh investigate --workspace .local/d19-workspace doctor
rh investigate --workspace .local/d19-workspace start --spec spec.json --runtime runtime.json
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
```
A complete offline investigation flow is: install the project (for example, `pip install -e .[test,mcp]`), prepare `spec.json` and `runtime.json`, then:

```powershell
rh investigate --workspace .local/d19-workspace start --spec spec.json --runtime runtime.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
rh investigate --workspace .local/d19-workspace submit RUN_ID TASK_ID --result result.json --task-version 1
rh investigate --workspace .local/d19-workspace work RUN_ID
rh investigate --workspace .local/d19-workspace resume RUN_ID
rh investigate --workspace .local/d19-workspace report RUN_ID
```

Inputs are user supplied offline JSON and explicit synthetic scenarios. The adapter does not call live sources or generation APIs. For monitoring, use `run-once`, then `review` and explicit `decide`:

```powershell
rh monitor --workspace .local/d19-workspace run-once MONITOR_ID --scenario cycle.json
rh monitor --workspace .local/d19-workspace review --monitor-id MONITOR_ID
rh monitor --workspace .local/d19-workspace decide ISSUE_ID --decision accept --note note
```
