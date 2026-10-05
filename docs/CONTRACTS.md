> 当前执行入口：[INTEGRATION_STAGE.md](INTEGRATION_STAGE.md)（2026-10-05，用户批准 S0–S6 实施）。下文历史阶段的“仅设计/不实现 GUI”等表述保留其历史范围，不限制本轮；实际通过状态按本轮固定候选记录。

> Current integrated design: [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md), D19 v1.0, 2026-09-10. The local GUI projection is specified separately in [GUI_API_CONTRACT.md](GUI_API_CONTRACT.md). This file preserves accepted legacy contracts and proposed extensions. D19 contracts are design requirements, not yet implemented schema guarantees; accepted D2/D18 behavior remains protected.

> D19 v0.2 proposed extension (2026-09-10; not implemented): see [Investigation plan, section 13](INVESTIGATION_EXPERIMENT_PLAN.md#13-双出口与产品内多-agent-工作流v02) for report_spec, role-scoped ModelTask, supported synthesis claims, section-to-evidence mapping, dual deliverables and immutable report versions. Extend existing domain objects; preserve accepted D2 behavior. These proposed fields are not yet executable schema guarantees.

## S1 report-block-v1（2026-10-05）

源 `version_id` 按文档身份和源字节哈希固定；`parse_revision_id` 独立绑定解析/分块配置与输出哈希。同一源的重解析追加新证据，旧证据 ID、文本、locator 与源文件不覆盖。默认检索使用当前源及其当前修订；显式 `revision_ids` 可访问旧修订，邻文窗口不能跨修订。重解析历史源不切换文档当前源版本。只读旧库不迁移，缺少修订表时从既有解析和证据推导 legacy 修订身份。

S1 首版报告使用 `report_contract=report-block-v1`，冻结报告保留该契约。读者正文由独立核验器接受且满足原文绑定检查的 claim 投影生成；自由正文与自由标题保存在 `raw_model_output`，不直接进入正式章节。章节标题为固定本地化标签。定位、连续引句匹配、finding 绑定和独立核验接受状态分别记录，引句匹配不能代表语义支持。

若证据含 `parse_revision_id`，新 claim 必须匹配该修订，调查任务与导出均检查；历史未携带此字段的证据继续保留原契约，不补造修订通过记录。冻结任务保存实际证据与修订，不因库重解析重新检索。

模型调用收据保存应用层 prepared request、prompt/template 哈希、运行/任务版本、profile、输入 refs、检索选择或明确空值、预算与授权结果，响应在解码前保存。原子领取与状态转移防重复派发；已发送但结果未知的调用保留额度与未决状态，不自动重发。密钥不写收据。收据不声称代表供应商内部输入；缓存与网络执行分别记录的引擎扩展尚待 S2 实现。

导出重新验证原始核验输入、claim、块及章节绑定；篡改后的正文不能直接导出。语言提示是启发式；未接受的翻译或被截出的草稿以问题记录使报告为 `partial`，而流程 `stage=completed` 可同时成立。无新版标记的历史报告继续按旧契约读取，不追溯声称满足新版门槛。

### report-block-v2 扩展

新投影使用 `report_contract_version=report-block-v2`，四类块为 `fact`、`explanation`、`method`、`gap`。前三类文本均从独立接受的 claim 组织；改分类不能绕过事实门槛。`gap` 仅由冻结 coverage 状态和受限问题代码投影，不复制模型自由缺口正文。导出重算原始核验输入及块绑定。v1 冻结报告继续只读兼容，不改写为 v2。

写作任务新增可选 `section_kind`／`block_kind`，只允许前三类；用户或模型不能提交 `gap` 来绕过核查。分类入口由当前核心候选整合；投影组件已独立通过 36 项，服务完整入口仍随核心固定候选验收。

# Data and application contracts — D1

> D19 v0.3 proposed extension: CompanyProfile, MonitorSpec, policy-bound Query/ModelTask, company relevance Finding and patent_monitor_digest reuse existing identities and review history. Search progress and judgment progress are distinct; human and model decisions remain separately versioned. See [Investigation plan, section 14](INVESTIGATION_EXPERIMENT_PLAN.md). These are design requirements, not implemented schema guarantees.

> D19 human triage clarification: every completed business judgment returns relevance independently from human_review_required and review reasons. Relevant and irrelevant patents can both require human review; unresolved uncertain judgments must require it. Program/policy checks may escalate a model recommendation, while pending judgments cannot masquerade as false. Persist the effective decision, concrete review question and model proposal separately; reuse existing review issue history. See section 14.6 of the investigation plan.

> D2 current scope: the executable fixture framework is accepted against K01–K07. Full provider, parsing, retrieval and recovery requirements below remain the later product contract. The following application boundary is required now for a future GUI wrapper.

## D2 application boundary for a future GUI

### D2 fixture finding and citation contract

The fixture model callable receives `(spec, candidate, candidate_evidence, reference_evidence)` as ordinary dictionaries/lists. Evidence includes the existing persisted `id`, `document_id`, `quote` and `locator`. The callable returns a finding dictionary with `disposition` (include/exclude/watch), `comparison_result`, `rationale`, `candidate_citations` and `reference_citations`. Each citation is `{ "evidence_id": "...", "quote": "exact original text" }`. Empty citation arrays explicitly mean missing support. The harness binds the finding's stable `id`, `candidate_id` and `document_id` to the analyzed candidate; model-supplied identities cannot change ownership. This small fixture contract does not require implementing the full D1 observation schema below.

The verify stage resolves candidate citations only against that candidate's persisted evidence and reference citations only against the frozen baseline evidence. Quotes must exactly match the referenced evidence text; locators come from that evidence record. A missing candidate citation or an invalid ID/ownership/quote sets `disposition=watch`, `comparison_result=insufficient_evidence`, and `verification={"status":"invalid","errors":[...]}` with stable reason codes, and creates a persisted issue tied to the real candidate document. A comparative result (advantage/disadvantage/similar/different_approach) also requires a valid reference citation. Valid citations receive `verification.status=valid`; this records structural verification only, not scientific entailment. Preserve the original model output separately if needed for audit; canonical findings and report conclusions must use the verified result.

The default synthetic model constructs citations from the evidence it actually receives. A deliberately missing-support fixture returns empty candidate citations and watch; no dependency on a special missing flag is allowed in the verifier. Model/source provider integrations remain deferred.

The CLI and a future GUI call the same application services. No UI implementation or HTTP server is required in D2. Reuse the existing Harness service where practical; do not introduce a separate framework just to expose these methods.

| Operation | Required boundary |
|---|---|
| Validate/save a specification | Accept a validated JSON-compatible ResearchSpec or an explicitly selected file; return its saved revision/reference and validation errors. Preserve manual edits and immutable run inputs. |
| Import/select local material | Accept user-selected supported text/normalized fixture inputs; return stable document/evidence references and declared coverage. Managed writes remain in the selected workspace. |
| Execute the fixture workflow | Accept a saved spec and explicit fixture runtime/adapters; return a structured run result with run_id, outcome and artifact references. A synchronous callable is sufficient now. |
| Read status/results | Return structured stage/outcome, findings/review and artifact references through a service method. Callers must not inspect SQLite tables, CLI output or LangGraph internals. |
| Record a human decision | Accept the stable issue ID and an explicit decision/note; persist it and expose the effective current state without rewriting frozen reports or global rules. |
| Export/get report artifacts | Return language, format and workspace-scoped path references. Rendering failure has a structured error; no automatic browser launching from the application service. |

Expose one optional progress observer on the run service, for example `on_progress(event)`. Events are JSON-compatible and contain `run_id`, `stage`, `status` and optional safe message/counts. Emit actual stage changes, including a terminal outcome; do not invent completion percentages. Without an observer the same workflow remains callable. Callbacks and Python objects do not become persisted provider payloads. A future GUI can dispatch the synchronous service in its own worker and consume these events; worker scheduling, cancellation and network transport are deferred.

Public results and errors must have JSON-compatible representations with stable IDs/codes and safe text. Internal exceptions/framework objects must not be the GUI contract. CLI formatting/printing belongs in the CLI, and application services must not depend on terminal input, stdout parsing or GUI globals. This is an in-process boundary, not a promise of a REST API.

### D2 concrete service projection

Reuse `Harness`: `status()` returns run summaries with `run_id`, `project_id`, `revision`, `outcome`, `stage`, `error`, `limits` and `artifacts`. Add `get_result(run_id)` returning the same fields plus frozen `report_data` as a dictionary and its `findings`/`issues` as lists. Stage is the error stage for failed runs and report for finished fixture runs. `artifacts` retains the existing `report` directory string and adds `files`, a list of `{language, format, path}` for existing exports; shared JSON/CSV use language null. `get_artifacts(run_id)` returns this same `{report, files}` object, keeping the implemented result and artifact endpoint consistent. The service resolves artifact paths from its managed workspace and run record, not from arbitrary caller-supplied paths. Callers never decode serialized database fields.

`review_list()` returns events as lists, and `review_decide(...)` returns the updated issue. This current review state is distinct from frozen run issues. Add `close()` so application clients do not access Store even for cleanup. Existing validate/save/import/run methods remain the public entry points; no generic command dispatcher, REST layer, worker or GUI is required.

For the following error-boundary step, extend existing HarnessError with a safe `to_dict()` representation (`code`, `message`, optional `field`/`stage`), and use stable typed errors for invalid inputs, unmet preconditions, missing run/issue and export failure. Exposed messages must not include raw external exception text or invalid input values. Validate the fixture file and basic candidate shape before creating a run; invalid input must not strand a running record. Keep the already implemented structured source-failure result. These changes define ordinary in-process error handling, not a new error/recovery framework.

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

## D17 开放采集契约（2026-09-10）

`search(config)` 返回 records、search_status、queries（请求范围、分页状态、失败和截断）。`download(manifest, output, limit=...)` 返回 outcome、valid_pdf_count、received_bytes、逐文献记录和产物。CLI 和未来 AI 工具复用函数。数据源 key 从环境读取，与 LLM key 分离；日志和配置不保存秘密。record 保留 title、doi、year、authors、type、locations 以及宿主筛选理由，案例可指定 expected_min_pages。许可和版本按实际下载位置记录；身份匹配/可解析不等于正文完整，发现预览或页数不足进入 review。具体字段见 [OA_COLLECTION](OA_COLLECTION.md)，本契约不改变旧 ReportData。

## S2 可选研究进程协议

`research-engine-jsonl/1` 的监督器使用配置的绝对 Python 路径与 argv 启动，不使用 shell。任务身份由 run_id、task_id、task_version 三项绑定；每个 RPC request_id 唯一，只允许 model_call、embedding 和 retrieve_frozen。父进程回传结果与核心 call ID；工作进程不持有供应商凭据或调查数据库路径。行大小、总输出、调用数和期限有界；终态后迟到消息、重复请求、非法 JSON、EOF 与非零退出分别作为失败记录，不能自动重新启动。

引用解析要求唯一冻结 evidence_id，且 document/version/parse revision/locator 与冻结输入相等；连续引句存在多个位置时进入复核。无解析修订的旧证据必须显式标 legacy，不能用缺失字段冒充新修订。外部章节与主张仍为 draft，引用通过只证明定位关系，下游语义核查与报告门槛继续适用。

JSONL 和 Python 审计钩子属于应用层约束；本机子进程不能被称为对恶意可执行文件的操作系统沙箱。只有受控、锁定的工作进程可以启用。容器的网络隔离另行记录实际宿主验收。实际研究进程验收与合成协议测试分别留存，不以协议测试代替库内部行为检查。
