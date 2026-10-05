# GUI 后端 A 阶段审计

日期：2026-09-24。依据当前工作树源码；仅审计，未调用来源或模型 API。工作树包含既有未提交 D19 修改，本文件不改变它们。

## 能力映射

| GUI 操作 | 判定 | 真实依据与边界 |
| --- | --- | --- |
| 能力及凭据存在性 | adapter-needed | `InvestigationService.doctor()` 返回模式、来源及环境变量存在性；模型在线状态为 `not_checked`。GUI 需按选定运行配置聚合，绝不回显 key。 |
| 调查列表、状态、结果、产物 | existing + adapter-needed | `status()` 列出全部 run，`status(run_id)` 返回 stage、budget、coverage、stage_trace；`get_result` 在未完成时抛 `RH_RESULT_PENDING`；`get_artifacts` 取结果产物。HTTP 层需分页、schema_version、稳定错误。 |
| 创建、推进、角色任务 | existing + adapter-needed | `create_investigation(spec,runtime,scenario)` 校验后产生 pending planning；`get_pending_tasks` 返回 task_id/version/role/payload/output_schema；`submit_model_result` 校验 schema 和引用，重复相同结果返回 reused，不同内容冲突；`advance_investigation` 使用现有 LangGraph。GUI 需串行队列和写请求幂等键。 |
| 模型 API 自动推进 | existing + adapter-needed | `advance_api_run` 循环取任务、调用 `run_model_task` 并推进；`reserve_model_call` 在 HTTP 前持久预留额度，失败亦占额；真实供应商认证未验收。仅在显式配置和授权时启用。 |
| 恢复与停止 | core-gap | `resume_investigation` 直接调用 `advance_investigation`，不是 cancel。`advance_api_run` 是无停止检查的循环；没有合作式停止入口或持久 stopped 状态。GUI 不可宣称可停止。 |
| 人工处理 | existing + adapter-needed | `review_list(monitor_id)` 和 `review_decide(issue_id,decision,note)` 转接 `ReviewStore`，决定枚举为 relevant/irrelevant/uncertain/defer，同决定和注释重复提交直接返回。清单身份是 monitor/company/document，**不是普通 investigation run 清单**。GUI 必须按 monitor 作用域显示，普通 run 不得混用。 |
| 报告和导出 | existing + adapter-needed | `build_report_data` 读冻结记录，`export_report` 生成标准产物并更新 result.artifacts；GUI 下载只能使用服务器签发的 artifact ID/白名单路径。已有同 run 双全文导出验收，科学覆盖仍 partial。 |
| 发现证据 | existing + adapter-needed | `get_discovery_evidence(evidence_id,runtime)` 返回 payload；非公开内容需授权 runtime；GUI 还需从 evidence_id 到文档和附件的受控解析。 |
| RAG 库 | existing + adapter-needed | `RagLibrary(read_only=True)` 有 `get_library_status`、`get_document`、`get_evidence_context`、`search_evidence`；状态返回 documents，但没有专门分页只读列表。`get_document` 提供版本信息；附件需安全服务。 |
| 事件/SSE | core-gap | `stage_trace` 是持久快照的一部分；没有可直接转发的 seq 增量事件或断线游标。薄封装可从状态快照生成带序号的观察事件，不可伪称已有实时阶段事件。 |
| 本地 HTTP、附件、令牌 | adapter-needed | 当前入口为 Python/MCP/CLI，无同源 GUI API；须绑定 loopback、限定 Host/Origin、会话令牌、服务端固定 workspace 和路径白名单。 |

## 线程、锁和数据约束

`InvestigationService.__init__` 即获取 `.investigation.write.lock`（非等待），创建 SQLite 连接并持有到 `close()`；`RagLibrary` 也持有 SQLite/索引资源。GUI 应在专用工作线程创建并关闭服务实例；不跨线程转移 SQLite 连接。一个 workspace 只保留一个服务写入者。读取与 SSE 从串行服务队列或独立只读快照获取，避免阻塞浏览器。浏览器不能指定任意本机目录。

人工决定只承诺 monitor 作用域；普通调查中 result.issues 不等同于 `ReviewStore` issue。证据定位应保留 document_id/version_id/locator，缺坐标时只跳页或段落。`partial` 为真实覆盖结果，不能改写为完成。

## 建议冻结的最小核心修改白名单

1. `src/research_harness/investigation.py`：增加只读、分页的 run/document/evidence 投影方法（若薄封装无法用现有公开方法完成）；不直接在 HTTP 层查询私有表。
2. `src/research_harness/investigation.py` 与 `src/research_harness/investigation_model_api.py`：增加持久合作停止请求及安全边界检查；检查位置包括 API 循环领新任务前和图阶段转换前。保留已发调用的 timeout 与调用账本，不撤销额度。
3. `src/research_harness/rag.py`：仅在 `get_library_status` 的 documents 无法满足分页/版本定位时，增加只读分页方法。保留 `read_only=True` 行为。

以上是建议，须由 Sol 冻结合同并批准具体方法后才写核心文件。无需修改科学算法、模型结果 schema 或冻结报告数据。

## 接口样例与空值

`GET /api/v1/runs?limit=20&cursor=...` → `{ "schema_version":"1", "items":[{"run_id":"inv-...","status":"partial","stage":"completed","coverage":{...}}], "next_cursor":null }`。列表空值表示确实无条目；读取失败返回稳定错误，不能返回空列表。

`GET /api/v1/runs/{run_id}` → `{ "schema_version":"1", "run_id":"...", "status":"waiting_model", "stage":"planning", "waiting_reason":"model_task", "budget":{...}, "coverage":{...}, "stage_trace":[...] }`。未知用量为 `null`，不能填 0。

`POST /api/v1/reviews/{issue_id}/decision` 的 body 示例为 `{ "decision":"defer", "note":"原文待核", "idempotency_key":"..." }`；仅 monitor issue 可用。`POST /api/v1/runs/{run_id}/stop` 在核心停止实现前必须返回 capability unavailable，不可调用 resume 代替。

`GET /api/v1/runs/{run_id}/events?after=17` 应先返回当前状态快照与真实的序号增量；若游标断档，要求客户端重新取快照。序号与事件日志需由新封装定义，不把 `stage_trace` 的数组位置假定为全局序号。

错误统一 `{ "code":"RH_RESULT_PENDING", "message":"...", "retryable":false, "request_id":"..." }`；不透出异常栈、密钥、授权头或私有绝对路径。

## 阶段验收依据

`docs/D19_QUERY_LOOP_PUBLIC_EXPORT_ACCEPTANCE.md` 已记录原 run 的标准公共导出通过，覆盖仍 partial。`docs/D19_MODEL_API_STAGE.md` 已记录五家适配器无网络协议及合成流程通过，在线调用待验收。GUI 离线联调必须注入无网络执行器；`synthetic` 配 `mode=api` 仍会调用真实模型，不能作为免费 fixture。
