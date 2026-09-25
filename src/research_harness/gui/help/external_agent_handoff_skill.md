# 技能：外部 Agent 交接

## 领取与回复

外部 Agent 先使用 conversation.list_pending，再 claim 指定 turn；取得有效租约后才能读取上下文、提交进度和回复，最后 ack。断开后只能恢复交付，不能重做已提交的受控操作。

## 权限

外部 Agent 只能使用 managed control/MCP 动作，不可执行任意 shell、读取凭据或控制桌面。工具目录存在不代表可以自动执行调查；用户仍需显式执行。
