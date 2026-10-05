# GUI 本地接口合同 v1

2026-09-25 状态补充：多上下文现状以 `GUI_MULTICONTEXT_EXECUTION_20260925.md` 为准，队列以 `GUI_U09_EXECUTION_CONTRACT_20260925.md` 为准；快速完成的操作可返回原业务结果，异步项返回 command_id，客户端需兼容。本文“启动时固定 workspace”保留为初版描述。运行时工作区创建、managed CLI/MCP、对话和外部消息桥的新增合同分别见 `GUI_W1_EXECUTION_CONTRACT_20260925.md`、`GUI_W2_EXECUTION_CONTRACT_20260925.md`、`GUI_W3_EXECUTION_CONTRACT_20260925.md`、`GUI_W4_EXECUTION_CONTRACT_20260925.md`；当前离线验收见 `GUI_AGENT_CHAT_ACCEPTANCE_20260925.md`。

日期：2026-09-24。工作区在服务启动时固定，浏览器不得传入磁盘路径。所有 JSON 响应含 `schema_version: "1"`；错误为 `{code,message,retryable,request_id}`，不得包含密钥、私有绝对路径或堆栈。

## 传输与身份

- 服务仅绑定 `127.0.0.1`；静态文件与 API 同源。限制 Host 与 Origin，所有写请求使用启动会话令牌。无需宽泛 CORS。
- `run_id` 是现有 InvestigationService 身份；`workspace` 仅由启动配置确定。未知值、定位不足、未配置能力均须显式表示，不填假值。
- 列表使用 `limit`（1–100）与不透明 `cursor`，返回 `items,next_cursor`。列表读取失败不得返回空列表。
- 写请求带 `idempotency_key`。同键同内容重放返回先前结果，不同内容返回冲突；不能因双击重复发起模型调用。

## 必要操作

| 方法与路径 | 内容与来源 |
| --- | --- |
| GET `/api/v1/capabilities` | 服务能力、来源及模型凭据存在性；仅布尔值或 `not_checked`，不返回 key。未实现能力为 false。 |
| GET `/api/v1/runs` | 现有 `status()` 的分页投影；保留 `status`、`stage`、`coverage`。 |
| GET `/api/v1/runs/{run_id}` | `status(run_id)` 快照，包括真实预算、`waiting_reason`、`stage_trace`；未知用量为 null。 |
| GET `/api/v1/runs/{run_id}/result` | `get_result`；尚未产生结果返回 `RH_RESULT_PENDING`。 |
| GET `/api/v1/runs/{run_id}/report-data` | `build_report_data(run_id)` 的只读投影，返回 `report_data`；用于报告主张到证据定位，保留冻结 canonical 事实。 |
| GET `/api/v1/runs/{run_id}/tasks` | `get_pending_tasks`，含 task_id/version/role/output_schema。 |
| POST `/api/v1/runs` | 已验证的 ResearchSpec、runtime 和可选无网络 scenario；调用 `create_investigation`。默认不得触发付费调用。 |
| POST `/api/v1/runs/{run_id}/advance` | 调用 `advance_investigation`；单工作区串行。API 自动执行仅在显式配置且另有调用授权时可用。 |
| POST `/api/v1/runs/{run_id}/tasks/{task_id}` | 经现有 `submit_model_result` 校验提交，保持 task version 与引用校验。 |
| POST `/api/v1/runs/{run_id}/stop` | 合作式停止：不领取新任务；在安全边界到达后返回 stopped；已发网络调用照既有超时和账本结算。未实现时返回 capability unavailable。 |
| POST `/api/v1/runs/{run_id}/resume` | `resume_investigation`；不清空预算或重复已完成任务。 |
| GET `/api/v1/runs/{run_id}/artifacts` | `get_artifacts` 产物清单，返回服务签发的 artifact ID。 |
| GET `/api/v1/artifacts/{artifact_id}` | 只从该 run 已登记产物提供下载；拒绝任意路径及目录越界。 |
| GET `/api/v1/library` | `RagLibrary` 只读文档/版本分页；标记 reference/discovery 与来源覆盖。 |
| GET `/api/v1/evidence/{evidence_id}` | `get_discovery_evidence` 或 RAG 公开方法；保留 document_id/version_id/locator。无附件/坐标则返回 locator_insufficient，不伪造高亮。 |
| GET `/api/v1/reviews` | 仅 monitor 作用域 `review_list(monitor_id)`；普通调查 issue 不伪装为可决定的 ReviewStore 项。 |
| POST `/api/v1/reviews/{issue_id}/decision` | 仅 monitor issue；使用实际 decision 枚举及既有持久历史。 |

## 观察事件

`GET /api/v1/runs/{run_id}/events?after=SEQ` 返回状态快照及后续观察事件；每条含 `seq,run_id,type,time,payload`。序号由封装持久记录，`stage_trace` 本身只是快照，不当作已有实时事件。断档返回需重取快照的错误；连接中断后重读状态，不靠前端计时器生成进度。可先用轮询快照实现观察；若没有可靠序号，`events` 能力标 false，不宣称 SSE 通过。

## 前端空值与安全

`partial` 始终与执行阶段并列展示；`completed` 阶段不等于覆盖完整。PDF 物理页与印刷页分开；XML claim/段落保留原定位。专利 `patent_claim` 和报告 `report_claim` 分开。外部文本作为不可信数据转义显示。GUI 不保存密钥，不能将任意本地路径发给文件服务。

当前已知核心白名单：`investigation.py` 与 `investigation_model_api.py` 仅为停止边界及必要只读投影；`rag.py` 仅在分页无法由公开方法实现时纳入。科学算法、报告事实与任务 schema 不在本合同修改范围内。

## 凭据与 MCP 增补

`GET /api/v1/model-credentials` 返回模型服务凭据状态，`POST`/`DELETE /api/v1/model-credentials/{provider}` 设置或清除本次 GUI 会话的 key。`GET /api/v1/source-credentials` 返回 OpenAlex API key、EPO OPS consumer key/secret 各自的 `session|environment|missing` 状态；`POST`/`DELETE /api/v1/source-credentials/{name}` 管理本次会话输入。写操作要求本地会话令牌；响应不含密钥。仅调查服务执行期间临时注入进程环境，操作结束恢复。`GET /api/v1/mcp-setup` 返回本机 Python、文献库、调查工作区和模型缓存路径，用于生成外部客户端 STDIO 命令。外部 MCP 不共享 GUI 会话密钥。

`POST /api/v1/runs/{run_id}/model-step` 在 API 模式下只执行一个待办模型任务或推进一个无待办步骤，并沿用调查核心预算。此接口需写入令牌与幂等键。GUI 新建页目前仅接受已验证合成场景；来源凭据配置并不等于开放真实网络调查。
