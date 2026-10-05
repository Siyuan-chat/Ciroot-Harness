# GUI 前端 B 阶段实现记录

## 2026-09-24 Figma 线框参考改版

参考用户指定的 Patent Agent v0.1 Wireframe，前端改为 64px 白色顶栏、220px 分组导航、中央工作区、右侧 Patent Inspector 和深色七阶段运行条；采用 `#f6f7fa`、`#dbe0e8`、`#2961e0` 色板。文献列表增加客户端当前页筛选和搜索，顶栏 Run 进入现有调查页。Ask Agent 明确显示未接入，因为当前本地服务没有问答接口。七阶段条为导航示意，真实阶段和覆盖仍只读服务返回值；不填充线框中的示例专利、企业或 AI 分析数据。原有阅读、专利比较、报告证据、人工处理、设置及能力门控保留。验证：`npm test` 3/3、`npm run check` 和 `npm run build` 通过，最终静态候选已更新至 `frontend/dist/`。

日期：2026-09-24。`frontend/` 为无构建依赖的原生 Web 工作台，使用同源 `/api/v1`；没有复制 AGPL 上游源码。服务需将 `frontend/` 作为静态目录提供。三栏布局、窄屏重排、键盘焦点、文献库、运行、报告、人工处理、设置和运行面板已接入。

接口使用 `schema_version=1`、分页游标、`run_id`、服务签发 artifact ID 和写入幂等键；错误保留 code/message，执行状态与覆盖状态分别显示。停止按钮仅在 capabilities.stop 严格为 true 时启用。页面不渲染远端 HTML，不保存密钥，不提交磁盘路径。前端创建流程只允许 `allow_network=false` 的 runtime。

验证：`cd frontend; npm test; npm run check; npm run build`。服务启动时使用 `--static-dir frontend/dist`。启动终端显示的会话令牌由用户在设置页输入，仅保存在内存。后端写入采用 `x-session-token` 与 `idempotency-key` header；任务提交使用 `task_version` 与 `result`。

C 阶段收口：报告读取服务新增的只读 `/runs/{id}/report-data`，按实际 `claims[].claim_id/evidence_refs` 和 `evidence[].evidence_id` 显示主张→证据按钮。点击后重新请求 `/evidence/{id}`，侧栏显示原文、document/version 身份和服务返回的 locator；缺 locator 明确提示，不伪造页码或高亮。能力使用 `capabilities` 内层对象；人工清单必须输入 monitor_id，决定枚举对齐服务的 `relevant/irrelevant/uncertain/defer`，并显示已有历史。API 请求测试 2/2 通过；JS 语法和静态构建成功。浏览器操作及真实后端联调由 Sol 独立验收。未运行真实模型、来源或 Zotero API。

首版页面补齐：文献详情从 `/library/documents/{id}` 读取版本和服务签发的 `file_url`；阅读页以证据 ID 读取原文、locator，并在已登记 PDF 可用时附 `#page=N` 打开。调查页展示真实查询记录、预算和待办任务。专利比较从冻结报告书目的 patent 类型、publication ID 与 document ID 选择公开文本，按 `/runs/{id}/documents/{id}` 的 `epo_sections` 并排显示 claims；缺失时标明缺项，不推断同族关系。报告页展示 `technical_report` 与 `literature_review` 的已核验 section、主张证据链，并调用服务 `/export` 生成中英标准产物。产物按 `type/language/format` 标识。当前若服务没有登记原件 URL，阅读页只给原文片段和 locator，并明确说明原件不可打开。

冻结案例复验修正：实际 ReportData 的专利证据 locator 为 `xml_node` 且 evidence 未带 `document_type`；候选身份来自 `bibliography` 的 `type=patent`、`publication_id` 与 `id`。前端改用这三个已冻结字段筛选。原始冻结 JSON 只读核对得到 `doc-919616a2d08e7c6784331bd4 → WO2026182370A1`。已结束运行（stage=completed 或终态 status）禁用推进/停止/恢复并说明原因；已停止运行只允许恢复。静态文件已重建，浏览器复验由 Sol 执行。

G04/G02 接线：运行选择后按 `/runs/{id}/events?after=SEQ` 读取持久观察事件，显示真实 stage/status 与事件序号，不生成进度百分比；轮询中断显示连接错误，409 断档先重取运行快照再从序号 0 读取。阅读页仅使用服务签发的 PDF `file_url` 与 `#page=N`、XML `originals[].url`；XML claim/段落通过 `/locate` 核对返回原文和 locator。没有登记原件的冻结证据摘录继续标示摘录范围。


## 2026-09-25 multi-context implementation record

- Added workspace/library/collection selectors sourced from the registry and context APIs. Selection updates explicit scope headers, clears stale visible library/object data, increments a generation, and guards late reads; run mutations capture the initiating scope. Browsing selection is independent from a run's reference snapshot.
- Drafts and view state are keyed by workspace/run/page (and library/collection for library views). Non-sensitive fields are persisted; secret inputs remain in memory only. Language changes preserve current input, focus/selection, composition state, details disclosure, and scroll.
- Added stable dynamic translation keys for scope errors and progress summaries; source titles/text, report body, user input, code and identifiers are marked/preserved as data. Existing UI still contains some legacy static text routed through the original dictionary and is not claimed as a complete stable-key migration.
- Bottom progress route is bound to the selected run and workspace, with localized actual stage mapping, explicit unknown-stage text, run-scoped event cursors, status/coverage separation, and native details disclosure state.
