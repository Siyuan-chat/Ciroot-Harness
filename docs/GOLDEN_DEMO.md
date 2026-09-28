# Golden Demo (offline)

Run the fixed synthetic investigation without submitting role tasks manually:

```powershell
rh investigate --workspace .local/golden-demo golden-demo
```

The command uses the packaged `golden-demo-spec.json`, `synthetic-runtime.json`, and `golden-demo-scenario.json`. It drives the existing `InvestigationService` with deterministic local role results, exports both `technical_report` and `literature_review`, and prints the run ID, actual outcome, evidence and review counts, coverage, and artifact paths. It makes no network or model API calls. All inputs and reports carry the service's synthetic marker.

One deliberately malformed synthetic XML candidate creates an open normalization issue. The expected result is `partial`; this preserves the service's coverage and issue semantics. Two other synthetic source documents produce evidence-backed claims with evidence ID, document/version, locator, and source excerpt.

Use the returned run ID to reopen persisted state in a later process:

```powershell
rh investigate --workspace .local/golden-demo result RUN_ID
rh investigate --workspace .local/golden-demo report RUN_ID --languages en
```

The first command reads the stored result; the second regenerates exports from frozen ReportData. The demo proves deterministic service orchestration and export behavior. It is not a scientific result or a live-source/model acceptance.
