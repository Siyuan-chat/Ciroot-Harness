# CirootHarness Research Workspace — information architecture

Status: IA accepted on 2026-09-28 with the implementation clarifications below. This document changes no runtime behavior.

## Problem and design principles

The current shell exposes seven peer destinations and persistent context controls, detail, run bar, and assistant. A new researcher must learn the application's object model before asking a question. The product should lead with a research question, make the investigation the central object, expose source-backed claims, and show incomplete coverage and human work without treating them as a success or a failure.

Principles: investigation first; evidence and uncertainty visible; review in context; assistant on demand; technical identities available on expansion; one source of truth in the existing application service. This is an incremental vanilla ES module redesign, not a new workflow engine.

## Current IA and evidence from the checkout

| Area | Current behavior | Friction |
| --- | --- | --- |
| Entry | `state.page = 'library'`; seven-item `nav` in `frontend/app.js` | No question-led start |
| Shell | Workspace/library/collection in context controls; global search, run, assistant, details, and bottom run bar | Multiple simultaneous entry points |
| Library | Browse/import/search; evidence search result exposes DOI or document ID and raw locator | Technical metadata dominates |
| Reader | Independent top-level page | Separates source inspection from claim/report context |
| Patents | Independent top-level comparison page | Makes a specialist tool look like a general destination |
| Runs/report/reviews | Separate pages; pipeline reflects internal stages; report and evidence compete with debug data | Investigation story is fragmented |
| Assistant | `chatOpen: true`, `chatListOpen: true`; executor visible in composer | Permanently uses research width |

The GUI API already exposes runs, result, report-data, evidence, artifacts, library and monitor reviews (`docs/GUI_API_CONTRACT.md`). Existing frontend tests cover chat, library, API and i18n contracts. `docs/GOLDEN_DEMO.md` and `tests/test_golden_demo.py` establish a deterministic service-driven, synthetic, offline run whose outcome is **partial**, with three candidates, two evidence-bearing documents, two verified claims and one open normalization issue. These numbers are acceptance expectations for the current fixture, never UI constants.

## Target IA and navigation map

Primary navigation (EN / zh-CN / JA):

| Route | EN | zh-CN | JA | Main task |
| --- | --- | --- | --- | --- |
| Overview | Overview | 概览 | 概要 | Start or resume research |
| Library | Library | 资料库 | ライブラリ | Import, browse, search, inspect documents |
| Investigations | Investigations | 调查 | 調査 | Open a run, view progress, sources, claims and activity |
| Reports & Review | Reports & Review | 报告与复核 | レポート・レビュー | Read output and cross-investigation review inbox |
| Secondary | Settings | 设置 | 設定 | Preferences, source and assistant configuration |

```text
Overview
 ├─ Enter question → Plan Investigation → prefilled Assistant draft → user sends
 ├─ Try Offline Demo → canonical Golden Demo run → Investigation
 └─ Recent investigation → Investigation
Library → document row / search hit → Document Inspector
Investigations → run → Overview | Sources | Evidence | Activity
                                  └─ Patent Compare, only when patent sources exist
Investigation claim → Evidence Inspector → registered original
Investigation review issue → contextual issue detail
Reports & Review → report → structured claim evidence chip → Evidence Inspector
                 └─ cross-investigation inbox → issue's investigation
Settings / project switch → scoped configuration
Ask AI → contextual assistant drawer; History popover; Advanced executor
```

Reader becomes Document/Evidence Inspector, opened from Library, Investigation, Report, claim or evidence. Patent Compare becomes an investigation tab only when source metadata identifies a patent; absent or unknown type does not produce a patent tab. Existing `workspace_id`, `library_id`, `collection_id`, `run_id`, conversation, evidence, export and review identities remain unchanged. The project name opens a hierarchy chooser; switching scope follows existing draft and context guards.

## Overview wireframe and first-use path

```text
┌─ CirootHarness / Polymer Membrane Research ▼ ─ Search ─ [Try Demo] [Ask AI] [···] ┐
│ Overview               │ What would you like to investigate?                      │
│ Library                │ ┌─────────────────────────────────────────────────────┐ │
│ Investigations         │ │ Enter a research question…                         │ │
│ Reports & Review       │ └─────────────────────────────────────────────────────┘ │
│                        │ [Plan Investigation]                                     │
│ Settings               │ See how CirootHarness works                              │
│                        │ [Try Offline Demo]  Offline · Synthetic · No API key      │
│                        │ Recent investigations                                   │
│                        │ • Membrane routes   PARTIAL   2 verified · 1 issue       │
│                        │ • AEM stability     COMPLETED …                          │
│                        │ Library: 23 documents   Open reviews: 2                  │
└────────────────────────┴──────────────────────────────────────────────────────────┘
```

All counts and rows above are illustrative layout data. Runtime values come from the read-only, scoped `/api/v1/overview` GUI projection; it returns at most five recent runs and nullable counts. A missing count displays “Unknown”, never zero by assumption. A missing legacy result cannot fail the whole Overview. Empty workspace shows workspace creation plus the offline demo entry. Empty library shows Import documents and Try Offline Demo. “Plan Investigation” only opens the Research Assistant with the question prefilled; the user sends it explicitly through the existing conversation/spec pathway. Typing or clicking Plan never creates a run or initiates a paid call.

## Golden Demo onboarding

The CTA appears on Overview, in the empty library, and as a small header action. Text: “Try Offline Demo” / “体验离线 Demo” / “オフライン Demo を試す”; nearby labels say offline, synthetic, deterministic, no API key. Activation calls `POST /api/v1/demos/golden` with the current workspace and an idempotency key. This thin GUI adapter invokes canonical `run_golden_demo` / `InvestigationService`, returns the real `run_id`, then navigates to that run. A repeated key returns the same run without duplication. No frontend fixture result or duplicated demo business logic. A failure stays a visible structured error and never opens a fabricated report.

## Investigation wireframe

```text
┌─ Investigations ────────────────────────────────────────────────────────────────┐
│ Compare Synthetic Membrane Routes                  PARTIAL · SYNTHETIC          │
│ 2 verified claims · 1 open issue   [Open Report] [Review issue]                │
│ Research question: Compare synthetic membrane routes.                         │
│ [Overview] [Sources] [Evidence] [Activity] [Patent Compare*]                   │
│ Scope: 3 candidates · 2 evidence-bearing documents · coverage: partial        │
│ Progress: Plan ✓  Search ✓  Read ⚠ 2/3  Analyze ✓  Verify ✓  Review ● 1        │
│ Findings / claims → Inspect evidence     Open issue → issue detail             │
└────────────────────────────────────────────────────────────────────────────────┘
* Only if the run includes patent documents.
```

Progress labels are a projection of available stage trace, coverage, candidates, claims and issue data. Do not infer “Read 2/3” unless the denominator is present and means candidates read; otherwise show “2 evidence-bearing documents; coverage partial”. Never turn a completed internal stage into overall completed when coverage or issues keep the run partial. Source failures, unsupported operations and waiting states retain their real meaning.

The run header links directly to its issues. `result.issues` are investigation issues and may be read-only; `GET/POST /reviews` apply to monitor review items. A GUI-only `/api/v1/review-inbox` projection may aggregate safely identified issues and must expose `actionable` and supported `decision_actions` explicitly. If monitor enumeration is unavailable, the inbox may initially include only run issues while the existing monitor route remains available. Show only backend-supported decisions, never decorative Retry/Exclude/Defer controls.

## Report, evidence and document inspection

```text
┌─ Nav ───────┬─ Technical Report (700–850px reading measure) ─┬─ Evidence ─────┐
│ Reports &  │ Title · PARTIAL · synthetic                       │ Source title    │
│ Review     │ Executive summary                                │ Version v1      │
│            │ Key finding: claim text                           │ Exact quote     │
│            │ Evidence-backed claims: claim [Evidence E12] ────→│                 │
│            │ Limitations and coverage                         │ Paragraph 2     │
│            │ Review issues                                    │ Used by C-02    │
│            │                                                  │ [Open original] │
│            │                                                  │ Advanced ▾     │
└────────────┴──────────────────────────────────────────────────┴─────────────────┘
```

Report body uses document typography, not nested cards. Current ReportData binds `section.claim_ids` → claim → `evidence_refs`; it does not provide character offsets within free-form section text. Therefore an “Evidence-backed claims” block follows each relevant section and contains clickable evidence chips. Do not inject heuristic inline citations by substring or regex. A claim card starts with verification state, claim text, and supporting-source count, then “Inspect evidence”. The evidence trace is a simple accessible HTML tree: claim → evidence → source title → version and human-readable locator. Inspector shows exact source quote, document version, locator, usage by claims, and a service-issued original link when available. Advanced details reveal stable IDs and raw locator. When no registered original or adequate locator exists, state that explicitly; do not invent a link or highlight. Preserve report-claim versus patent-claim distinction and escape untrusted source text.

## Assistant interaction

Default: closed. “Ask AI” opens a contextual right drawer at desktop widths, overlays at tablet widths, and switches Main/Assistant on mobile. Closing retains the draft and conversation scope. Header: “Research Assistant”, History popover, close. History does not permanently reduce message width. Executor choice and API budget live in Assistant settings/Advanced; the selected executor and synthetic data mode remain disclosed before an action that incurs calls. The demo chooses its canonical synthetic runtime regardless of assistant preference. Existing conversation persistence, switch semantics, idempotency and scope checks remain authoritative.

## Status semantics and language

| State | Meaning | Visual token |
| --- | --- | --- |
| Completed | Run completed with stated coverage | Green |
| Partial | Usable output with a gap or issue | Amber |
| Running | Work is in progress | Teal/blue |
| Needs Review | Human action or inspection needed | Purple/amber |
| Failed | Execution failed | Red |
| Unsupported | Capability unavailable | Muted gray/red |
| Stopped | Explicitly stopped | Gray |

Status has text and icon as well as color. `partial`, `failed`, and `completed` get separate tokens. Unknown/limited coverage is displayed explicitly. All newly touched UI strings are keyed in `i18n.js` for EN, zh-CN and JA; existing hardcoded legacy text is a separate follow-up. Technical IDs are disclosed through Advanced details. Typography targets 14–16px body, 12–13px secondary metadata, and 11–12px only for IDs; spacing uses 4/8/12/16/24/32/48px. Preserve navy `#001F48` and teal `#017675`; prefer whitespace over nested borders.

## Narrow-window behavior and accessibility

| Width | Composition |
| --- | --- |
| 1440×900 / 1280×800 | Sidebar + main; assistant or evidence inspector on demand. Report inspector may remain alongside report if reading measure is preserved. |
| 1024×768 | Compact navigation + main; assistant/evidence uses one drawer at a time. |
| 390×844 | Main/Assistant switch; navigation menu; evidence and review details overlay with close/back. Never four simultaneous columns. |

Keyboard focus reaches all actions; active nav uses `aria-current`; drawers and History expose `aria-expanded`, a clear close control, focus management and Escape behavior. Focus ring and contrast remain visible; long EN, Chinese and Japanese strings wrap without hiding primary actions. Preserve drafts and scroll state when drawers or language change.

## Migration plan and acceptance gates

1. **PR 1, this document:** IA and wireframes, accepted with four clarifications: Plan Investigation draft handoff, structured evidence chips, distinct review contracts, and read-only Overview projection. No runtime, schema, data, or service edits.
2. **PR 2, Overview and onboarding:** Four primary destinations, first screen, empty states, canonical demo adapter if needed, default-closed assistant and History popover. Preserve old internal routes until all links are migrated. Test frontend check/test and relevant GUI API tests; inspect actual render in all three languages and four target sizes.
3. **PR 3, investigation workspace:** Run overview, progress, source coverage, claims, contextual issue links, conditional patent tab. Counts from the actual demo response. Verify partial remains partial.
4. **PR 4, report and evidence:** Reading surface, inline references, inspector and evidence trace. Verify a Golden Demo report claim leads to the exact source quote, document version and locator without terminal/JSON.
5. **PR 5, visual cleanup:** Consolidate CSS tokens/layout/components and overlapping responsive rules; typography, spacing, status and button hierarchy, keyboard and overflow review. Do not start with polish.

Each implementation PR gets a bounded writer assignment with Objective, Allowed files, Forbidden files, Behavior to preserve, UX target, Required tests, Acceptance criteria and Commit message. The acceptance owner checks the fixed diff, real rendering, `npm run check`, `npm test`, relevant Python GUI tests, EN/zh-CN/JA and 1440×900, 1280×800, 1024×768, 390×844. If rendering is unavailable, report “visual QA not independently rendered”. The same canonical Golden Demo run is the preferred cross-page QA story.

### PR 1 design review questions

1. First action: enter a question and Plan Investigation on Overview, or try the offline demo.
2. Golden Demo: Overview, header, and empty Library; service-driven synthetic run.
3. Investigation: Investigations list → run workspace.
4. Partial: amber text/icon badge, coverage gap and issue count; never completed.
5. Review issue: run header/detail and cross-run Reports & Review inbox.
6. Claim to evidence: structured claim evidence chip → evidence trace/inspector.
7. Report: constrained reading column with an evidence-backed claims block per section.
8. AI assistant: Ask AI opens an on-demand drawer/switch.
9. Library: primary navigation, import/search/browse.
10. Technical IDs: Advanced details, with human-readable title/locator first.

## Non-goals and open implementation dependencies

No React/Vue/Svelte/Tailwind migration, full rewrite, new workflow state machine, dark mode, animation system, fake demo/evidence, database schema change, live scientific claim or release. PR 1 does not alter product code.

PR 2 adds a thin Golden Demo GUI endpoint and read-only Overview projection. Investigation issues and monitor ReviewStore items have different decision contracts; PR 3/4 must show ordinary issues without suggesting unsupported actions. The exact source-original URL must be checked against actual evidence responses before implementing the inspector.
