# GUI 后端实现记录

日期：2026-09-24。实现位于 `src/research_harness/gui/`；接口字段以 `GUI_API_CONTRACT.md` 为准。工作区由启动参数固定；FastAPI 同源提供静态页与 JSON API，只通过 `127.0.0.1` 启动入口暴露。所有写请求要求 `x-session-token` 和 `idempotency-key`；幂等结果保存在工作区 `gui-idempotency.sqlite`，跨进程重启可复用。

服务调用由进程内锁串行，每次请求在调用线程创建并关闭 `InvestigationService`，避免跨线程 SQLite 连接。读取现有 run、任务、报告、RAG 文档与 monitor 人工清单；产物下载按已登记 artifact 的 ID 回查并限制在 `reports` 下。未实现的事件序号能力显式为 false。

核心白名单改动：`investigation.py` 增加 `request_stop`、停止时禁止推进/任务提交、恢复时保留已有任务与预算；`investigation_model_api.py` 在每次循环取任务前识别 stopped。停止可在下一次安全边界生效；单工作区同步调用期间的 HTTP stop 请求需等待当前操作返回。没有取消已发网络请求或返还额度。

验证：使用 `.local/d19-runtime/venv/Scripts/python.exe`，设置 `PYTHONPATH=src`，运行 `python -m pytest -q tests/test_gui_contract.py`，4 项通过；覆盖 Host/Origin、错令牌、创建幂等及冲突、待办任务、停止和进程重建后恢复的预算/任务稳定性、产物越界拒绝、冻结报告未就绪错误。模型 API 既有回归 7 项通过。`GET /api/v1/runs/{run_id}/report-data` 使用 `build_report_data` 提供冻结报告事实。未创建 RAG 库时 `/library` 明确返回 `index_status: not_indexed` 与 `document_count: null`，不伪装为空库。原生浏览器与干净安装仍由集成验收完成。

文档阅读接口：`/api/v1/library/documents/{document_id}` 返回文档及版本，移除原始 `source_path`；版本的 `file_url` 只取工作区 `raw` 下已登记的版本文件。`/api/v1/runs/{run_id}/documents/{document_id}` 使用新的最小只读核心方法返回既有 discovery payload；EPO 的 `epo_sections` 和 XML 正文保留，下载的论文 PDF 以受控 `file_url` 提供，不回显 base64。`POST /api/v1/runs/{run_id}/export` 复用 `export_report`，返回签发 artifact ID；只在冻结报告已存在时可用。当前契约测试 5 项通过，含版本文件、EPO claim locator 和 PDF 内容读取。

冻结报告证据回退：`get_discovery_evidence` 先按原 `discovery_evidence` 表及可见性策略读取；若缺少对应行，再从已冻结 `ReportData.evidence` 按 evidence_id 读取，并检查非公开项的运行策略。这样未附带 RAG index 的只读案例副本仍可从 C6 主张打开其 XML claim 原文及 locator；测试采用该案例 C6 的真实字段结构在临时库重建，不修改原工作区。产物列表另给 `name`（由已登记 path 的文件名取得），界面不再显示“未命名”；内部 path 不回显。

无网络 HTTP 全流程：`tests/test_gui_contract.py::test_http_synthetic_flow_export_restart_without_network` 使用现有 `examples/investigation` 合成 spec/runtime/scenario，经 TestClient 调用创建、读取/提交每个角色任务、推进、读取双报告、标准导出及产物下载，再重新创建应用读回已完成状态。测试将 `requests.sessions.Session.request` 替换为直接失败函数，若发生外部 HTTP 调用则测试失败。6 项 GUI 契约测试通过；此项证明本地服务离线流程，浏览器实际交互另由独立验收记录。

运行状态现在从持久 `runtime.data_mode` 返回 `data_mode` 与 `synthetic`，列表和详情一致，重开可读。冻结 bibliography 中若有专利文献但 `discovery_documents` 未保留该行，`get_discovery_document` 从同 run 冻结证据生成只读 `epo_sections` 摘录，明确标 `content_scope: frozen_evidence_excerpts`，不把摘录宣称为完整权利要求全文。WO2026182370A1 的文献身份和 C6 XML locator 已用隔离临时库中的真实字段结构测试。Monitor `ReviewStore` 的 HTTP 人工决定经过重开仍保留原机器判断和人类事件；重复同键只保留一个有效决定，普通 investigation issue 返回 404。当前 GUI 契约测试 7 项通过。

观察事件由 GUI 封装的 `gui-events.sqlite` 持久保存 `seq/run_id/type/time/payload`。`GET /api/v1/runs/{run_id}/events?after=SEQ` 返回当前服务快照及后续事件，状态变化才追加 `status_snapshot`；重启保留序号。传输为客户端轮询，`transport: poll`，游标越界返回 409 并要求重取快照；事件不是新的业务状态机。已登记 EPO `source_xml` 生成不含路径的 original ID，`/originals/{id}` 仅从选定工作区、对应 run 的 `epo` 目录读取并核对 SHA-256；`/locate?kind=...&value=...` 从已解析 `epo_sections` 返回 claim/段落文本，缺失为 404。PDF 通过既有受控 `file_url` 并可用 `#page=N` 跳物理页。当前 GUI 契约测试 9 项通过，含事件断线重连/重启和 XML 原件/locator。

冻结案例的 `ReportData.bibliography.id` 是 canonical `doc-*` 身份，`discovery_documents.document_id` 则是来源身份（专利 publication ID、论文 OpenAlex ID）。只读 `get_discovery_document` 现先按同 run 冻结 bibliography 中的 `publication_id` 或 DOI 精确匹配唯一登记来源文档；匹配成功才返回其已登记 `source_xml` 和 PDF 内容，无法唯一匹配才显示 `frozen_evidence_excerpts`。在 `.local/gui-frozen-acceptance` 的 SQLite 只读副本和 XML 文件副本上实测：`doc-919...` 返回 claims/description 两个 opaque URL，均 HTTP 200；`doc-a360...` 返回 PDF file_url，HTTP 200。未改原冻结工作区。相关契约测试现共 10 项通过。封装的 SQLite 连接通过 FastAPI lifespan 在服务关闭时释放。



## 2026-09-25 multi-context implementation record

- Added trusted local registration through `--context-config` (or an adjacent `gui-contexts.json` for packaged desktop builds). Browser requests carry stable workspace/library/collection IDs only; paths are resolved from the local config. The registry API returns names, associations, collection counts, and index status, not filesystem paths.
- Scope validation rejects unknown workspace, library, collection, and cross-workspace library associations. Run storage, idempotency namespaces, event ledgers, and session credentials are keyed by workspace. Per-library RAG objects use a bounded four-entry LRU; document identity is resolved within the selected library and collection.
- GUI run snapshots are stored separately in `gui-contexts.sqlite` with library, collection, member document/version IDs, and index version/status. This is metadata-only: the current GUI admits synthetic investigation creation; scientific core does not consume the selected library snapshot for that mode. Enabling a real library as scientific input requires a separately authorized core API change.
- Validation: GUI TestClient suite covers registered-scope rejection, same document identity across libraries, collection filtering, workspace-scoped credentials/idempotency, and snapshot immutability across app restart.
