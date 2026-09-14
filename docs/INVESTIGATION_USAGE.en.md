# Offline investigation host

Install the project's investigation dependencies, then call the local
`InvestigationService` through `rh investigate ...`:

```powershell
rh investigate doctor --workspace .local/d19-workspace
rh investigate start --workspace .local/d19-workspace --spec spec.json --runtime runtime.json
rh investigate tasks --workspace .local/d19-workspace RUN_ID
```

The MCP entry point is `python -m research_harness.investigation_mcp
--workspace PATH`. P1 supports offline host mode with explicit synthetic/replay
inputs only. It does not call live sources, generation APIs, or OS schedulers.
Submit the exact task version and preserve missing values, uncertainty, exact
source quotes, and locators. Initial local work can block this single process;
do not run CLI writes while the same library is open in MCP.
