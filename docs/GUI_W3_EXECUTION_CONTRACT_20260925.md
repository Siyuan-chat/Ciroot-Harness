# W3 GUI 对话与 API Agent 执行合同

日期：2026-09-25。W1/W2 固定候选已通过离线验收。本阶段新增归属 workspace 的持久 conversation 与受控 agent 行为，不建立第二套调查科学状态机。W3 的离线验收使用明确标注的 synthetic scripted executor；真实收费模型调用另需额度授权与独立验收，不能由本阶段自动发起。

- 对话接口允许创建/list/get conversation、提交用户 turn、读取消息/状态、显式执行已形成且通过现有 schema 验证的 ResearchSpec。消息带稳定 turn/request 幂等身份；workspace 作用域强制校验，凭据不落盘。source/evidence 以 ID 和 locator 引用，模型可见上下文记来源，不复制整篇原文。
- 问题/范围不充分时只澄清缺项；仅讨论不创建 run。显式执行时创建现有 InvestigationService run，使用当前绑定库快照和 U09 队列推进；不可静默允许真实网络或付费模型。对话关联 run/command/task，记录真实返回；失败/partial 不说成功。
- scripted executor 是离线验证工具：可根据结构化测试输入产生确定性 spec 和角色结果，标注 fixture，不对任意用户自然语言宣称可完成研究。API executor 用已配置 provider 与会话凭据、显式模型/调用上限和超时，先检查权限/预算；对话调用单独记账并纳入总上限，无法判定用量保持 UNKNOWN。重启后不自动重发未确认模型请求。
- “停止回复”停止后续工具领取；“停止调查”调用核心安全停止；已发请求按原超时/账本处理。切工作区或库不改变已绑定 conversation/run 的范围。GUI 显示可展开对话、当前 scope/执行器/预算、消息与证据/报告卡片；850×600 下仍可输入和停止。
- 本阶段只在现有 GUI 服务受控 API 内实现，不通过任意 shell、桌面坐标或文献正文指令控制操作。真实资料入口和库导入继续属于独立待办。

Terra 先独占后端 `src/research_harness/gui/app.py`、必要新增 `src/research_harness/gui/conversation.py`、定向测试；若确需修改调查核心或公开 schema 必须先报告理由和精确范围。Terra 固定候选交付后，Luna 独占前端 `frontend/app.js/api.js/i18n.js/style.css` 及前端测试。Sol 只读整合验收：两个 workspace 会话隔离、离线 scripted 澄清→显式执行→角色任务→报告/证据，幂等/失败/停止/重启及 GUI 切库不串上下文。W4 外部 agent 双向消息另行实施。
