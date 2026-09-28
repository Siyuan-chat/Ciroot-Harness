# GUI Golden Demo verification

## Accepted checks

- The Python public smoke and related GUI/API checks passed: 52 tests. The bridge executes the canonical Golden Demo with model/source credentials unset and external network access guarded in tests; verifies persisted `partial`, real evidence/report content, open normalization issue, authenticated/idempotent execution, and service reopen.
- Browser interaction against the real local backend opened the saved run, displayed `partial`, followed a claim to its evidence ID, document/version, locator and source excerpt, and displayed the two actual exported Markdown reports.
- Frontend syntax checks, 39 tests and the production build passed. A separate Edge DOM regression uses explicit test fixtures to exercise localized CTA clicks, the canonical GET/POST request contract, delayed GET/POST leave/re-enter recovery, and retained POST retry identity; it reported no page errors. It is frontend interaction evidence, not a real investigation execution.

## Pending checks and delivery boundary

Native Windows WebView2 started with the localized demo entry, but the complete native click/run/close/reopen path has not been accepted. Published `v0.1.1-desktop-preview` binaries have not been rebuilt or replaced by this change. Source/browser acceptance must not be advertised as updated release acceptance.

The user deferred PR C screenshots, hero and video until frontend optimization. No public visual assets are delivered by PR B. The 30-second comprehension and three-minute new-user experience targets have not been measured with unfamiliar users. Full Public Launch Acceptance remains pending.

See [GUI Golden Demo](GUI_GOLDEN_DEMO.md) for source launch and API boundaries. CI remains deterministic smoke coverage, not the complete heavy/live suite.
