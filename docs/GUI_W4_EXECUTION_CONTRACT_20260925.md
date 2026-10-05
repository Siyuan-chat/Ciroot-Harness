# W4 外部 Agent 双向对话执行合同

日期：2026-09-25。W1/W2 与 W3 离线 scripted 路径已完成。W4 让已显式连接的外部 agent 从 GUI 会话领取用户 turn，调用 W2 managed tools 后把进展/回复提交回同一 conversation。无外部客户端连接时只显示等待，不启动 shell 或把通用 MCP 工具列表当作消息已送达。

- GUI 会话选择 `external` executor；用户消息持久落库并形成待领 turn。消息领取接口需认证、绑定 workspace/library/collection、conversation_id、turn_id 和 actor，单 turn 单领取者，有期限租约；重领只恢复交付，不自动重放已经提交的 tool 操作。claim/ack/reply 使用稳定 request/idempotency ID，同 ID 不同内容冲突；重复提交同一回复只保留一条。
- managed MCP 桥新增受控 `conversation.list_pending/claim/context/progress/reply/ack` 等动作，仍走当前 GUI 服务与 W2 scope/认证。外部回复不能伪造 run 完成；工具结果须引用 W2 实际 command/run/evidence/report ID，前端显示真实状态。文献内容不赋予操作权限，密钥不返回 agent 消息。
- 外部断连时 GUI 显示等待连接/领取；可显式切换执行器，保留原会话消息和已用预算，不能两位执行器同时领取同一 turn。客户端不能被 GUI 自动唤起时明确说明需要客户端主动连接。关闭/重启后保留待办，租约过期可重新领取，但不能重做已提交受控操作。
- 只用本地 synthetic host 和 managed MCP bridge 的离线端到端验证；真正 Codex/Claude Code 客户端接收/回复须在其已安装可验证接口上另验，否则状态为“客户端端到端待验收”。不调用真实研究 API/付费模型，不使用 Computer Use，不推送 GitHub。

Terra 先独占后端 `src/research_harness/gui/app.py`、`conversation.py`、`control_mcp.py` 与定向测试；Luna 后续独占 `frontend/app.js/api.js/i18n.js/style.css` 及前端测试。Sol 对固定候选只读验收并区分协议与实际客户端层。
