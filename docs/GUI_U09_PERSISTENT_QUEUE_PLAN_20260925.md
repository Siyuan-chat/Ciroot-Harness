# U09 持久队列与恢复：已批准并实施

日期：2026-09-25。本文件保留批准前的方案基线；用户随后批准 U09。实施范围以 `GUI_U09_EXECUTION_CONTRACT_20260925.md` 为准，结果见 `GUI_U09_ACCEPTANCE_20260925.md`。以下“现状”和“拟议”描述的是实施前状态。

## 最小合同

- 队列只排 GUI 调用现有应用服务的**写入命令**，不复制 LangGraph 阶段或科学状态。每项记录 `command_id`、操作类型、注册 `workspace_id`/`run_id`、必要对象版本、脱敏参数、原请求幂等键、创建时间、状态与错误。浏览库读请求不入队。
- 同一 GUI 进程同时最多执行一项命令；其余按入队顺序显示 `queued`。统一的本地持久队列覆盖多个注册工作区，避免两个 workspace 各自运行一项。服务与 GUI 都显示排队位置、当前对象及 `waiting_reason`；切页面或库不取消命令。
- `stop` 必须有高优先级合作式通道，能在活动命令的安全边界生效；取消尚未开始的命令只将队列项标为 `cancelled`，不修改核心 run。已发出的外部调用仍按原预算/超时结算，不能把前端 Abort 当作撤销。
- 队列持久化不得包含密钥、原文副本或任意磁盘路径；执行时只从已注册 scope 解析资源。会话凭据失效时标 `waiting_credentials`，不借用另一 workspace 的密钥。客户端重复提交同 scope/幂等键返回同一队列项或既有结果，冲突 body 返回稳定错误。
- 关闭或崩溃后不自动发起潜在付费请求。重启先对队列项与核心 run/任务版本、已登记结果和预算总账核对；可证实未执行的项等待明确恢复，可证实完成的项标完成，无法区分的项标 `needs_review`，不得盲目重放。恢复沿用原 run 和预算，不建新 run 清零。
- 建议沿用 GUI 封装层一个有上限的 SQLite 队列和现有应用服务接口；不引入第二套科学流程状态机或后台调度服务。只对已列举写操作建立可重放 dispatch，不把 Python 闭包序列化进数据库。

## 拟议接口与验收

拟增 `GET /api/v1/queue`、`GET /api/v1/queue/{command_id}`、`POST /api/v1/queue/{command_id}/cancel`、`POST /api/v1/queue/resume`；现有写端点在忙时返回可定位的 `queued` 命令身份。实施前需冻结各写端点的入队范围、stop 的优先级、关窗行为及 `queued/waiting_credentials/needs_review` 的稳定 code 与前端文字。原工作区文件锁继续保护 GUI 与外部 MCP 冲突；若外部进程占锁，显示 busy/waiting，不能在未确认锁释放及版本未变前执行。

离线验收用两个临时 workspace、可控阻塞/失败的本地应用服务和无网络合成任务：A 活动时 B 排队，读库仍可用；取消 B 后不执行；重启后队列/幂等键/预算不丢；模拟执行后崩溃时不重复调用；缺凭据不跨项目借用；外部 MCP 占锁显示 busy；stop 在安全边界可观察。测试需要确认队列状态、核心持久记录和最终 UI，而不只检查 SQLite 行数。未验证真实付费并发安全前，不扩大为多个活动任务。

拟修改白名单：`src/research_harness/gui/app.py`、`frontend/app.js`、必要 `frontend/i18n.js`/`frontend/style.css`、`tests/test_gui_multicontext.py` 与一个定向队列测试。若必须修改调查核心、公开 schema 或额外文件，先提交精确原因和差异供批准。本计划不执行代码修改、真实调用或 GitHub 推送。
