# GUI Golden Demo

This GUI entry reuses the deterministic [canonical Golden Demo](GOLDEN_DEMO.md). It is an offline synthetic integration demonstration, with no model API key, model API calls or external source requests. It does not validate scientific results or live patent-search coverage.

## User path

1. Open the current CirootHarness GUI and choose **Try Offline Demo** (中文：**体验离线 Demo**、日本語：**オフライン Demo を試す**).
2. Choose **Run** to execute the fixed scenario. No JSON or executor setup is needed. If a saved result exists, the demo entry opens it without running again.
3. Inspect the actual outcome. The canonical scenario intentionally produces `partial` because a malformed synthetic XML source remains an open normalization issue.
4. Browse the frozen ResearchSpec, source/query attempts, evidence, review issues and both report types.
5. Follow a claim to its evidence ID, document ID/version, locator and exact source excerpt. The reports and source statements remain the canonical English synthetic material even when navigation is localized.
6. Close and reopen the GUI/service, then choose the demo entry again to read the persisted result.

The dedicated `public-golden-demo` data directory belongs to the GUI workspace. The demo does not copy the selected private library. It retains existing runs; explicitly starting a new run does not rewrite an older investigation. Every demo view carries SYNTHETIC / OFFLINE / DEMO labeling. Counts and status come from InvestigationService, not from JavaScript fixtures.

## Local source launch

From the repository root, after installing Python GUI dependencies:

```powershell
python -m pip install ".[investigation,gui]"
npm --prefix frontend run build
python -m research_harness.gui.desktop --workspace .local/public-demo-desktop
```

The native desktop entry requires Windows WebView2. The same frontend can be inspected through the loopback server:

```powershell
python -m research_harness.gui --workspace .local/public-demo-browser --static-dir frontend/dist --port 8765
```

Open `http://127.0.0.1:8765/` in a local browser. Install-time downloads are separate from offline demo execution. The previously published `v0.1.1-desktop-preview` ZIP is not updated by merging this feature; source launch/local builds and published release availability must be distinguished.

## API boundary

- `GET /api/v1/golden-demo`: read the latest saved demo, or `demo: null` before execution; never runs a new investigation.
- `POST /api/v1/golden-demo`: empty body, session token and idempotency key; calls the canonical runner. Caller-supplied workspace paths, specs, executors and scenarios are not accepted.
- Demo responses project the persisted status, frozen spec, result, report data and actual Markdown exports. Filesystem artifact paths are not part of the public display.

The GUI shows request-in-progress while running and the recorded service stages afterwards; it does not fabricate progress percentages or replay simulated stage timing. Review displays the existing issue code, reason and unresolved status. It introduces no alternative decision model.

## Verification boundary

Python bridge tests cover service execution, outcome, evidence/report binding, request replay, authentication, isolated storage and reopen. Frontend tests cover localized entry, canonical request, badges and real result rendering. The public workflow remains **deterministic smoke CI**, not the full heavy/live test suite. Actual browser/native checks and distribution limitations are recorded in the [GUI verification record](GUI_GOLDEN_DEMO_ACCEPTANCE.md). Public screenshots are deferred until frontend optimization; full Public Launch Acceptance remains pending.
