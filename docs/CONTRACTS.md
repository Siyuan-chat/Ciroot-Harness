# Data and application contracts — D1

This document defines framework-independent boundaries. The input schemas in [schemas](../schemas/) are normative interchange contracts. The implementation may use Pydantic internally. Serialized data must never depend on LangGraph, LlamaIndex or provider SDK classes.

## 1. ResearchSpec and RuntimeConfig

- ResearchSpec contains the user's task, conditions, reference selection, languages and execution policy. See [research-spec.schema.json](../schemas/research-spec.schema.json).
- RuntimeConfig contains provider/model selection, endpoints, local retrieval settings and environment-variable **names**, not credentials. See [runtime.schema.json](../schemas/runtime.schema.json).
- Each saved spec has schema_version, revision, status and project_id. Revision is monotonically increasing per project. A run binds an immutable revision and content fingerprint.
- A draft is structurally valid but not executable. A ready spec must have no unresolved_questions and pass semantic/capability checks. An example marked draft must not trigger network investigation.
- A dialogue session separately records user messages, answers, assumptions and field provenance. A field is classified as user_explicit, artifact_derived or engineering_default. Do not store hidden reasoning or credentials.
- Document paths are resolved inside the selected data workspace. Explicit local import may read user-selected files elsewhere; managed writes stay within the workspace.
- UTC timestamps use RFC3339; report display may use the configured IANA timezone. Dates without time remain dates, not invented midnight observations.
- Missing values are null or explicit status values, never zero, empty fabricated measurements or an invented confidence percentage.
- IDs and enum values stay language-neutral. Display labels and explanations are translated separately.
- Secret values do not belong in specs, reports, manifests, provider URLs, checkpoints, exception text or exported dialogue.

### Semantic checks beyond JSON Schema

1. Source capabilities cover requested document types and mandatory scope; unsupported language/territory coverage is surfaced, not silently ignored.
2. Threshold criteria have a comparator, decimal target, unit and enough explicitly specified comparison conditions. A missing critical condition stays unresolved or becomes a declared not_comparable policy; it is not guessed.
3. Qualitative criteria have no numeric target. Relative comparison names the relevant baseline concept and preserves matched conditions.
4. Criteria IDs are unique. Reference selection resolves to document versions, or the run explicitly records an empty baseline and no relative-superiority claims are allowed.
5. Credentials refer to available environment variables. Placeholder model IDs, unavailable embedding models, invalid endpoints and incompatible provider settings are diagnosed before paid calls.
6. cloud_excerpt_allowed=false is compatible only with local model execution for evidence-bearing calls. This project defaults to true.
7. An estimated monetary cap requires pricing inputs and reservation/accounting; it must not be described as a guaranteed provider billing cap.
8. Provider-specific filters/queries are validated; a model's schema-valid text does not imply a valid API query.
9. Input/revision changes cannot silently relax a user-specified constraint or change data disclosure policy.

## 2. Durable records

Terra must export JSON Schemas for these public records from the implementation and test round-trips. The following fields and semantics are required; internal tables may be normalized differently.

| Record | Required information |
|---|---|
| Document | document_id, source identities, kind, title, original language, publication date if known, authors/applicants, DOI or publication number/kind if known, family IDs if supplied, public URL, provenance |
| DocumentVersion | version_id, document_id, raw content fingerprint, acquisition timestamp/source, raw relative path, parser/version, available_sections, missing_sections, coverage, errors |
| Evidence | evidence_id, document_version_id, original text/quote, locator, source language, section role, extraction method/version; optional table context and normalized value |
| BaselineSnapshot | baseline_id, selected collection IDs, exact document_version_ids, timestamp, fingerprint |
| Query | query_id, source, language, expression, structured filters, purpose, parent query if expanded, source capability/validation result |
| SourceAttempt | run_id, query_id, page/cursor, started/ended time, complete/partial/failed/unsupported, reason, returned candidates, continuation, safe request metadata |
| Observation | criterion_id, raw_value, raw_unit, conditions, evidence IDs, normalized_value/unit and transformation if used, metric_result and explanation |
| Finding | finding_id, document_version_id, spec/baseline fingerprints, relevance, observations, comparison_result, machine_disposition, rationale, candidate and reference evidence IDs, verification |
| ReviewIssue | issue_id, stable issue key, document/finding IDs, rule/criterion identity, issue type, evidence fingerprint, status, machine suggestion, localized question, timestamps |
| ReviewEvent | event_id, issue_id, action, decision, note, actor, time, explicit scope, prior event; append-only |
| RunManifest | run_id, spec/revision/fingerprint, baseline_id, safe runtime/model/parser/index versions, source coverage, outcome, budgets and actual usage, checkpoints, artifact paths |
| ReportData | run_id, snapshot time, referenced versions, new/changed finding IDs, technical map, coverage and limits, review snapshot, localized display fields |

Record identity is independent of prose, output language and transient list order. A content fingerprint is an engineering identifier, not a scientific quality score.

### Evidence locator

For PDF: document version + physical PDF page number (1-based) + bounding box when available + section/table label. Preserve printed page label separately if it differs.

For XML: document version + stable element/paragraph/claim ID or XPath + section role. Do not invent PDF page numbers.

For plain text: document version + line/character range. For metadata-only records: locator explicitly says metadata/abstract; do not pretend it is a full-text citation.

A translated quote links to the same evidence_id, records its target language and remains distinguishable from the original quote. If OCR/parse quality is insufficient, coverage/quality is explicitly marked and queued where it affects a decision.

### Document and family identity

Normalize DOI casing/prefixes without losing the original identifier. Patent identity includes jurisdiction, publication number and kind code. An application ID is not a publication ID. A family groups related texts for reporting but does not deduplicate away differences in claims, jurisdiction, publication date or granted/published version.

Do not merge records based solely on similar titles. Preserve matching evidence and unresolved identity conflicts. Date/title corrections are metadata updates, not necessarily a new technical development.

## 3. Findings and conservative comparison

A finding contains four separate dimensions:

- relevance: relevant / irrelevant / uncertain.
- observation.metric_result: meets / does_not_meet / not_comparable / not_reported / not_applicable.
- comparison_result: advantage / disadvantage / similar / different_approach / not_comparable / insufficient_evidence.
- machine_disposition: include / exclude / watch.

A missing measurement is not a failed threshold. Different test conditions are not evidence of superiority. An explicitly irrelevant subject may be excluded without extracting every unavailable performance metric; a relevant subject with a material evidence gap becomes watch with an issue.

Machine-readable values must reference exact source evidence. Unit conversions use a documented deterministic transformation and preserve the original. No arbitrary unit matching or LLM-only arithmetic. Qualitative claims cite text and identify their source role (claim, description, experimental example, paper result).

Programmatic checks enforce evidence ownership, locator resolution and quote matching. Model verification examines entailment and comparability. Independent case evaluation remains necessary; agreement between two model passes is not scientific ground truth.

## 4. Human review semantics

Stable issue key:
project_id + document_id + rule/criterion identity + issue_type.
Rule identity includes the criterion/rule ID and its semantic fingerprint; a report-language change does not change that identity. The current evidence fingerprint and associated finding versions are tracked separately.

- Repeated identical evidence does not create duplicate issues or overwrite human decisions.
- New material evidence may reopen the same issue with a new event explaining the change. Cosmetic translation changes do not reopen it.
- Human action enum: include / exclude / watch / request_more_evidence.
- include/exclude/watch resolves the current issue with an explicit decision; request_more_evidence keeps it open and records a follow-up request for the next manually started run.
- A human watch decision is a resolved decision to keep monitoring, distinct from an open unresolved watch suggestion.
- Effective disposition uses the applicable human decision for that rule/evidence scope; retain the machine disposition and reason separately.
- A reopened issue retains the old human decision as history but labels its current applicability stale until reviewed or explicitly carried forward.
- A review mutation addresses a unique issue ID; optional family-wide scope requires an explicit user command.
- Global rule changes create a new ResearchSpec revision through the intake flow. They never occur as an implicit side effect of a review action.

All language views refer to the same issue/event IDs. CSV import, if implemented, must use IDs and validated decisions; free prose must not be interpreted as executable code. CSV export must neutralize spreadsheet formula prefixes in untrusted text while preserving exact evidence in canonical JSON.

## 5. Report translation contract

Canonical facts and identifiers are generated once. Translations fill display fields keyed by zh/en/ja for the requested languages. Numeric values, units, formulas, IDs, decision enums, source URLs and list membership remain identical across views.

Original titles/names may be accompanied by translations but are never replaced. Report headings, reason descriptions, errors shown to ordinary users, review questions and guide text are localized. Internal diagnostic details may remain English in a separate log.

ReportData is written before rendering. Partial failures yield an explicit outcome/coverage warning. Empty successful results, source failures and incomplete translations have different representations. Old report files remain immutable snapshots; a newly rendered review view has a new timestamp.

## 6. Adapter boundaries

Use minimal Protocols or equivalent interfaces only where replacement is required.

### Model adapter

Inputs: task role, trusted instructions, untrusted evidence payload, expected schema, limits, operation_id.
Output: validated structured payload, provider/model identity, usage or explicit unknown usage, safe error/capability metadata.

Implement OpenAI-compatible and Anthropic adapters for v1. Structured-output support is provider/model-specific. Bound repair attempts count against the same budget. A JSON mode fallback must still validate the result; it must not invent missing fields.

### Source adapter

- capabilities(): document types, query syntax, supported filters/languages, full-text sections, pagination and identifiers.
- search(query, cursor, limit): candidates + continuation + completeness.
- fetch(record, limits): raw assets/structured text + actual coverage + provenance.

Search errors are typed: authentication, authorization, rate_limit, temporary, unsupported_query, not_found, invalid_response. Do not collapse errors to empty lists. API-specific translation belongs here; providers need not understand one universal Boolean dialect.

### Parser and retrieval

Parser output: document version + evidence list + coverage/quality/errors.
Retriever input: query + allowed baseline version IDs + filters + top_k.
Retriever output: evidence IDs + retrieval diagnostics.
Search must never leak discovery-library material into a frozen reference-only query.

### Storage / application

Application services own versioning, identity, effective decisions, run/accounting and report construction. Framework-specific checkpoint storage is separate from the authoritative evidence/finding data.

A workspace supports one active mutating run in v1. Concurrency happens inside that run. A second local process gets a useful busy response; stale locks have a documented recovery rule. Read-only report/status access may proceed.

## 7. Required CLI contract (not yet implemented)

The exact package name and internal modules may change; the following user-facing operations and option meaning must remain documented consistently.

```text
rh doctor --runtime runtime.json --workspace workspace
rh chat --runtime runtime.json --workspace workspace --lang zh
rh validate --spec research.json
rh import <file-or-directory> --workspace workspace --collection baseline --kind paper
rh run --spec research.json --runtime runtime.json --workspace workspace
rh resume <run-id> --runtime runtime.json --workspace workspace
rh status --workspace workspace
rh review list --workspace workspace --lang ja
rh review decide <issue-id> --decision watch --note "..." --workspace workspace
rh report <run-id> --workspace workspace --languages zh,en,ja
```

chat accepts pasted/dictated text and performs clarify/revise/run/status/review through application services. A direct run command uses the same preflight and frozen spec rules.

doctor is read-only/local by default. An explicit --online option may test configured APIs with stated request scope. It must not dump environment variables or issue research/model calls during ordinary configuration validation.

Proposed exit codes: 0 successful operation; 2 invalid config/input; 3 missing dependency/credential; 4 partial run; 5 failed run; 130 cancelled. JSON machine output exposes stable error codes; user messages follow the selected language.

## 8. ResearchSpec lifecycle

draft -> ready -> immutable run snapshot.
Revising a ready spec creates a new draft/ready revision; no in-place overwrite of a run input. The intake service records a concise change summary. Version conflict checks avoid losing manual edits.

Manual edits are authoritative input on the next load if valid. Content fingerprints detect edits made without incrementing revision; the application assigns a new revision or asks the user to resolve an actual conflict. It must not silently replace manually edited values with older conversation memory.

A configuration-only example is not a data demo. A fixture replay is not live API validation. Every exported artifact records its execution mode and whether the underlying data are synthetic.


## 9. Limit accounting details

max_queries_per_source is cumulative across all search rounds in a run, including follow-up queries. max_search_rounds is an additional depth limit, not a multiplier for query allowance. Download limits count received bytes, including incomplete and retried downloads. Model limits include analysis, verification, translation and repair attempts for that run. Intake calls are recorded against the dialogue session with bounded attempts per user turn.

max_estimated_cost_usd applies to generation-model cost estimates using configured prices. Data-source charges and the provider invoice remain separate and may be unknown. The interface must not call this a guaranteed total-spend cap. Active execution time is cumulative across resumes and excludes idle time between user-triggered resumptions; timeout and crash-accounting precision must be documented.
