# GUI 三语与多上下文实施合同

日期：2026-09-25。依据 `GUI_UX_MULTICONTEXT_HANDOFF_SOL.md`，本轮授权本地实施和离线验收。用户已有未提交修改均为权威输入，禁止重置、覆盖或顺带整理。Luna 是唯一产品代码写入者；Terra 只读初验；Sol 维护本合同、统合验收。每轮固定候选交付后再验收，不检查写作中的候选，也不做进度轮询。

## 身份和切换

- `workspace_id` 标识已注册调查工作区；`library_id` 标识已注册实体文献库；`collection_id` 必须连同 `library_id` 解释；`run_id` 必须连同 `workspace_id` 解释。API 不接受浏览器传入的任意路径。现有单库客户端保留显式默认 scope；传了未知 ID 必须报错，不能回退。
- 当前视图是 `{workspaceId, libraryId, collectionId, runId, page, objectRef}`。浏览库选择和 run 冻结参照独立。参照保存库、文档版本、成员与索引快照；修改参照建立新 run/版本。
- 切换先保存非敏感草稿和视图状态，增加 generation，取消旧读请求，清空旧内容，然后读取新 scope。读响应必须同时匹配 scope 和 generation；写操作捕获发起时 scope 并归档到该 scope。事件游标按 run 分区。
- 非敏感草稿按 workspace/run/page 分区，可本地恢复。密钥仅保留在当前进程内存，不进浏览器持久层、URL 或日志。语言切换不触发运行，也不清空编辑中的输入、焦点和展开状态。

## 执行与检索

- 首版支持多实体库和多 run 浏览，一个进程只执行一个写入调查；其余显示 queued/waiting。原工作区锁保留。凭据注入保持串行，未隔离前不扩大并发。
- 首版默认单库或库内分组检索。跨库检索在具备各库独立检索与可解释聚合前显示不可用，不静默只查其中一库。相同 document_id 必须由 library_id 与 version_id 区分。
- 只做已注册 scope 路由和有界 RAG 实例缓存，不重建冻结索引或修改既有调查。未知库、无权限、空分组和失败分别显示。

## UI 与底栏

- UI 文案以稳定 key 和具名参数翻译中文、英文、日文；原文、报告、用户输入、技术 code 和 ID 不翻译。未知 code 保留原值并配通用说明。
- 桌面宽屏三栏，中屏双栏、详情可收起；850×600 的主要操作和底栏可访问。正文 14–16px，导航 14px，元数据至少 12px；统一断点，支持 125%/150% 文字放大。
- 底栏仅绑定当前 workspace/run。阶段按服务的 `planning/source/acquire_normalize/analysis/verification/completed` 映射；未知阶段原样显示，`partial`、`failed`、`stopped` 不显示全绿。折叠状态跨重绘保留，阶段与覆盖分别呈现。

## 文件边界与验收

允许 Luna 修改 `frontend/`、`src/research_harness/gui/`、`tests/test_gui_*.py`、`packaging/` 中实现本合同必要的文件，以及 GUI 专属实现记录。`pyproject.toml` 仅在构建必需时做最小 GUI 依赖改动。核心科学模块、旧 run、原文、索引、凭据、非 GUI 测试与其余文档均保护；新增核心接口缺口先向 Sol 报告精确原因，不自行扩围。

Luna 自检并交固定候选；Terra 对固定候选做命令行/无头浏览器初验 U01–U11 与失败清单；Sol 独立核对最终候选和适用边界。fixture、真实本地服务与最终包分层报告。禁止 Computer Use、真实研究 API/付费模型调用、GitHub 推送。原生 WebView2 窗口未亲测时单独标明。

## 最终统合验收

2026-09-25 最终 GUI 候选已交付。Luna 报告前端 7/7、GUI Python 14 项通过，最终 onedir EXE 启动并在两个已注册 scope 下分别返回上下文与 run 列表。原仓库 U08 脚本在 B 的异步状态呈现前读 DOM，原样复跑失败；历史记录保留在 `.local/gui-layout-acceptance/multicontext/quick-review.log` 与该目录的 `results.json`。后续临时副本通过不作为仓库脚本通过证据。仓库脚本正式修正及独立复验见 `GUI_MULTICONTEXT_QUICK_REVIEW_20260925.md` 的收口补记。

当前可确认：GUI 层的多 workspace/library/collection 身份、单库切换、run 分区、基本排他写入与等待提示、三语和无头布局、EXE 的双 scope API 可用。U07 仅冻结 GUI 参照元数据；合成调查核心尚未消费选定库，不能称真实文献库参照调查通过。U09 观察到排他执行与 waiting 提示，尚无完整持久队列恢复验收。U11 未在原生 WebView2 窗口完成交互验收。真实科学调查、外部来源与付费模型未运行。

本轮按授权边界停止，不修改科学核心或冻结资料。若要使 U07 完整通过，需单独批准对调查核心的参照输入合同与相应验收范围；该缺口不能用 GUI sidecar 快照代替。

后续阶段更新：用户已单独批准 U07 核心参照输入开发。离线输入合同与版本隔离的结果见 `GUI_U07_ACCEPTANCE_20260925.md`；本节上述历史结论保留为批准前状态，真实科学调查仍未验收。
