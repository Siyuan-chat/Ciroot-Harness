# W2 managed 本机控制通道执行合同

日期：2026-09-25。W1 固定候选已通过。W2 只增加连接到**正在运行的同一 GUI 服务**的结构化 CLI 与 managed MCP 桥；既有 standalone `investigation_cli.py`/`investigation_mcp.py` 保持兼容，不改科学核心或 U09 队列。

- GUI 服务为唯一写入协调者。CLI/MCP 通过 loopback HTTP 调用现有 API，不直接实例化 InvestigationService、写 SQLite 或运行任意 shell。服务关闭时明确失败，不隐式启动第二服务。
- 控制动作覆盖 workspace list/create；library/collection list；run create/status/tasks/submit/advance/stop/resume/export；queue list/detail/cancel/resume；evidence/report read。导航 `view open` 需要 client_id 和前端事件订阅，后端必须先校验目标对象所属 scope；未连接客户端只返回可读对象身份，不伪称已切页。
- CLI 接收结构化 JSON 输入文件或 stdin，stdout 只写一个 JSON envelope；诊断到 stderr。写请求必须有外部 caller 生成的稳定 idempotency key；不把密钥放 argv。操作结果区分即时 result 与异步 command_id，保留错误 code/retryable。每次请求绑定 workspace/library/collection 与 actor/request ID，拒绝越权对象 ID。
- 实例连接描述符放在 GUI 用户数据根，指向 loopback 地址及私有认证引用；运行期权限与生命周期保护认证，退出撤销，重启令牌轮换。不得把 GUI token 传入模型上下文或产物日志。无窗口的 `--no-browser` 服务也应提供相同通道。
- managed MCP 仅转发白名单受控动作；不能因通用 MCP 工具测试通过而声称 Codex/Claude Code 已真实接收 GUI 消息。W3/W4 对话留待后续阶段。

Terra 独占 W2 后端/CLI/MCP 文件写入并自测固定候选；Luna 此时不写产品代码。允许修改 `src/research_harness/gui/app.py`、`desktop.py`、新增 `src/research_harness/gui/control.py`/`control_mcp.py`、对应新测试和必要 `pyproject.toml` 入口；若精确需要更多文件先报告。Sol 完成独立 HTTP/CLI/MCP 合并验收与最终包检查。仅 synthetic host 离线数据，不使用真实研究 API、付费模型或 Computer Use，不推 GitHub。
