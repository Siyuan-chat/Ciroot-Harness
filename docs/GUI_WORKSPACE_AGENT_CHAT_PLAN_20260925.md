# 工作区创建与对话式 Agent：Sol 交接方案

后续任务统一清单见 `GUI_DEVELOPMENT_BACKLOG_20260925.md`，同时纳入真实资料调查、文献导入/库分组管理及跨库检索；本文件保留 W1–W4 详细设计。W1 已有独立执行合同，避免重复派工。

日期：2026-09-25。用户新增要求：用户可创建工作区；接入模型 API 或 Codex 等 agent 后，agent 能在后台通过命令行操作 harness，用户通过 GUI 对话框交互。本文保留最初方案；用户随后要求继续开发。W1–W4 与 API 对话规划的本地离线候选、实际命令和限制见 `GUI_AGENT_CHAT_ACCEPTANCE_20260925.md`。真实收费模型与实际 Codex/Claude 客户端仍待独立验收。

## 当前事实与目标

当前工作区仅从启动注册配置读取，没有 GUI 新建入口或创建工作区 API。已有调查 CLI/MCP 直接创建 InvestigationService；MCP 持有服务直到进程结束。GUI 新增持久队列位于 app.py，二者尚未共用命令调度。Ask Agent 未接入，调查表单只允许 synthetic。API 模型适配器、角色任务协议、证据链、导出和停止机制已有实现，应复用。

目标交互：用户点击“新建工作区”，输入名称并选择已有参照库或空库；进入工作区后，在对话面板描述研究问题。agent 读取授权范围、澄清必要问题、形成 ResearchSpec；用户明确要求执行时，后台创建 run 并执行。对话展示简短进展、待处理问题和证据/报告卡片，中央页面及底栏显示同一 run 的真实状态。用户无需手填角色输出 JSON。

“命令行操作 GUI”采用语义操作：创建/选择工作区、选择文献范围、创建/推进/停止任务、读取证据、打开报告。命令返回稳定 ID 和 JSON，GUI 订阅结果。首版不依赖鼠标坐标、DOM 点击或任意 shell 执行。GUI 界面状态和核心业务状态分别管理，导航不启动研究或改变冻结参照。

## 一条共享操作链路

```text
GUI 表单 / 对话框 ───────────┐
API agent 的受控工具调用 ────┼─ 本机操作服务 ─ U09 队列/幂等/作用域 ─ 既有 harness
CLI JSON 客户端 / MCP 桥 ────┘                 │                    │
                                      操作与事件 ID          run/task/evidence/report
                                              └──── GUI 与对话状态读回 ────┘
```

将 GUI 的注册/操作服务抽为可复用模块或为其增加薄客户端接口；先冻结最小改动，不重写业务核心。已入队的 advance/model-step/resume/export 继续走 U09；创建、角色提交及人工决定沿用其已有同步/幂等边界，不为统一外观强行复制大 payload 到队列。返回统一 envelope，区分即时 result 与异步 command_id，客户端不得假定所有成功响应都有 command_id。

现有 standalone CLI/MCP 保留兼容。新 managed 模式连接本机服务，由服务成为写入协调者；不得让旧 MCP 在同一个活跃 GUI 工作区持续占写锁。旧独立写入者仍由文件锁明确拒绝或等待。无 GUI 窗口时可运行同一个 headless 服务；不能另起第二套任务状态机。

## W1：新建工作区（第一交付）

- 顶部工作区选择器旁提供“＋新建工作区”；空态提供同一入口。表单只需名称、可选说明、参照库选择（已有库或空库），显示保存位置说明。
- 默认由后端在用户数据根下生成 workspace_id 与独立目录；名称不是路径，允许同名展示但 ID 唯一。浏览器和模型不能提交任意磁盘路径。自定义目录选择可后移。
- 初版给空工作区注册空的默认库，状态明确为未索引；关联既有库保持只读，不复制或重建原文/索引。新建空库不意味着已实现 GUI 导入。
- 注册记录必须在用户可写数据目录持久保存；启动时导入既有可信注册配置，与运行时新增记录按稳定 ID 合并。配置和目录创建失败可恢复，不留下看似可用的半成品；并发重名/重复请求用幂等键处理。
- 创建成功即在选择器出现；显式“创建并进入”才切当前客户端，不改变其他客户端上下文、旧 run 或原库。重启后仍可选择。首版不包含删除/迁移工作区。
- 拟议接口：`POST /api/v1/workspaces`，请求 `{name, description?, reference_library_ids?, idempotency_key}`；回复注册身份、库关联和状态，不回显私有目录。具体鉴权/header 形式由 Sol 与现有合同统一。

## W2：后台 CLI / MCP 控制合同

能力集合先覆盖 workspace list/create、library/collection list/select、run create/status/tasks/submit/advance/stop/resume/export、queue list/detail/cancel/resume、evidence read、report read。复用现有应用方法；缺少方法精确增补，不通过 shell 直接写 SQLite。

每次调用绑定 workspace/library/collection/run、actor、request/idempotency ID；角色提交还需 task_version。所有参数结构化校验。调用结果包含状态、command_id 或 result、相关对象 ID、稳定错误和可重试性。前端和 agent 使用相同授权及作用域校验。

拟议 CLI 示例仅为设计，不是现有可用命令：

```text
rh control workspace create --input request.json
rh control run create --workspace-id ws-... --input research.json
rh control command status --workspace-id ws-... --command-id cmd-...
rh control view open --client-id ui-... --workspace-id ws-... --run-id inv-... --page report
```

stdout 只输出结构化结果，stderr 写诊断；以 argv/subprocess shell=False 运行，密钥不放命令参数。连接描述符放在用户私有位置，含实例地址及受保护认证引用；服务校验 scope，连接撤销/重启后旧凭据失效。不要向模型上下文回传 GUI 会话令牌。

`view open` 只发送已校验对象的导航事件，带目标 client_id。用户正在浏览其他任务时显示“后台结果已就绪”，只有用户开启跟随或明确要求打开时切页面，不抢占焦点。无界面在线时保存结果并返回可读对象链接。

MCP managed bridge 转发上述操作给本机服务；可先支持外部宿主主动连接和读取待办。实际 Codex/其他客户端连接必须用其已安装、可验证的接口验收，不把通用 MCP 测试写成客户端端到端通过。

## W3：GUI 对话与 API Agent

- 对话面板可展开/收起，显示当前工作区、参照范围、关联任务、执行器及预算；与证据检查器有明确切换方式，850×600 仍可输入和停止。原文/用户消息不随界面三语切换改写。
- conversation_id 归属 workspace；消息、工具调用结果、错误、关联 command/run/task 持久化。记录模型可见内容来源，避免把原文完整重复抄入每条日志；凭据不进入会话存储。
- 流程为输入→必要澄清→有效 spec→执行/查看结果。已有明确指令和预算就继续执行，不增加每次工具调用确认；缺少关键范围/额度时只问对应问题。仅讨论或改需求时不启动调查。
- 使用既有模型供应商适配与角色协议；工具目录是受控操作白名单。自然语言“已完成”不能替代命令结果，partial/evidence_gap 必须保留。文献中的指令不具有操作权限。
- 持久记录 conversation-turn 与 tool-call 幂等身份；网络中断或重启不能重复发起收费请求。复用现有调用账本，对话澄清与研究执行分别列账、共享总预算上限，未知用量保留未知。
- “停止回复”停止生成/领取后续工具；“停止调查”请求核心安全停止；未开始命令可取消。已发模型请求按原超时和计费记录处理。重启按 U09 合同等待显式恢复，不自动消费预算。
- 对话任务选择绑定明确 scope；不能因用户浏览另一个库而改变正在运行的参照或使用另一工作区的凭据。

## W4：外部 Codex 等 Agent 与同一对话框

提供 executor 选择：配置的 API 模型、外部 agent。外部模式需双向桥：GUI 持久记录待处理用户消息；已连接外部 agent 领取指定 turn，读取必要上下文，通过 managed tools 调用 harness，提交回复/进度。只暴露工具供外部调用，还不等于 GUI 对话已接通。

首版外部 executor 使用显式连接的客户端/可验证适配器；同一 turn 只有一个领取者，租约过期仅恢复会话交付，不重复已提交工具操作。claim/ack/version 去重是消息传输元数据，不建立第二个科学任务编排器。断开时显示等待外部 agent，可显式切换执行器；切换保留上下文及已用预算，不同时启动两位 agent 执行同一任务。

如果所选客户端不支持被 GUI 后台唤起或推送用户消息，则明确显示“需连接/领取”，不要用 MCP 已注册冒充自动往返完成；在实际客户端适配验收后再开放对应按钮。此阶段不要求授予任意 shell 或桌面控制权。

## 分工和验收

Sol 冻结共享操作合同和修改白名单，整合固定候选并独立验收。Luna 负责前端工作区/对话与 managed 客户端；Terra 负责后端注册、操作服务和 executor 桥。共享文件由 Sol 指定唯一写入者，避免两人同时修改 app.py；可以按 W1→W2→W3→W4 顺序交付，不要求并行。本文件不启动代理。

| 门槛 | 必须观察到的结果 |
| --- | --- |
| W1 | UI 创建两个工作区；名称相同也不混淆；幂等重试只建一个；空库可进入；重启保留；旧库与旧 run 不变 |
| W2 | CLI/MCP 创建或推进 run，GUI 显示同一 command/run；队列并发、外部锁、重复提交与越权 ID 正确；GUI 关闭但服务运行仍能调用 |
| W3 | 离线 scripted executor 由对话输入完成澄清、创建、全部角色、报告/证据呈现；无须用户编辑 JSON；工具失败不能说成功；语言切换/切库不丢消息或串任务 |
| W4 | 真实已选外部客户端收到 GUI 消息，调用 managed tools 后回复同一 conversation；断连/重连不重做已执行操作；只有通用协议测试时保持客户端验收待定 |
| 恢复与额度 | 停止、重启、重复消息、预算耗尽、凭据缺失各有可复现本地测试；真实模型小预算验收另行记录 |

优先级：先 W1 补齐用户创建入口，再 W2 统一控制通道，再交付 W3 对话式 API agent，最后 W4 外部客户端双向联动。真实资料入口与库导入需要并列计划，不能因聊天完成而宣称真实研究可用。保留现有科学事实、冻结资料与收费授权边界。
