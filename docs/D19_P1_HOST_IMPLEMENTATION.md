# D19-P1 host implementation

Luna's host layer is a thin JSON/STDIO adapter around
`InvestigationService(workspace)`. The CLI and MCP server share the same
service methods and do not call sources, models, schedulers, or HTTP. MCP keeps
one service instance and its async handlers call synchronous methods directly,
which preserves SQLite thread affinity. Local work may block the process;
long imports belong in the CLI, and CLI writes must not run concurrently with
an open MCP library.

The eight role prompt files describe planning, paper and patent search, evidence
analysis, business judgment, synthesis, writing, and verification. They are
host guidance, not a second orchestration engine. Shared schemas, package
registration and the top-level `rh` dispatcher are integrated by Terra.

Validation status: focused adapter checks can use a fake service; end-to-end
offline C1/C2/C3 acceptance requires Terra's `InvestigationService` and the
separate D19 runtime. Live sources and model APIs are outside P1.
