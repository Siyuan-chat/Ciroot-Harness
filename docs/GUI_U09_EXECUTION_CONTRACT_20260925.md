# U09 执行合同

日期：2026-09-25。用户已批准 `GUI_U09_PERSISTENT_QUEUE_PLAN_20260925.md`。本文件冻结首版实现选择；原方案中真实网络、科学流程、持久队列安全边界不变。

## 命令范围

- 入队：已有 run 的 `advance`、`model-step`、`resume`、`export`。队列项只保存注册 scope、run ID、操作、必要小参数和原幂等键；不保存密钥、原始文献或角色输出。
- `create`、角色结果提交、人工决定仍以现有同步写入与幂等合同处理；遇活动写入返回 `RH_GUI_BUSY`。这些请求可能包含 spec、证据/模型输出或人工备注，不复制到队列库。浏览与读请求照常可用。
- `stop` 高优先级：活动操作期间可登记停止意图并立即返回已接受；在操作安全边界、领取下一项队列前调用现有核心停止。未开始的本 run 排队推进可取消。已发外部调用不撤销。

## 持久状态

- 使用 GUI 封装层一个全局 SQLite 队列，放在默认 GUI 工作区；跨已注册 workspace 共享单活动执行者。`queued`、`running`、`waiting_credentials`、`waiting_external_lock`、`needs_review`、`completed`、`failed`、`cancelled` 为队列状态，不改核心 run stage。
- 同 scope+幂等键+相同操作/参数返回同一 command；同键不同内容为冲突。已完成结果与现有幂等账本一致。新命令返回可查询的 `command_id` 与状态；前端明确显示队列位置和等待原因，完成后按原 scope 刷新，不抢占用户当前页面。
- 重启不自动执行残留队列。原 `queued` 项等待显式 resume；原 `running` 项先和既有幂等结果、核心任务版本/预算核对，不能证明安全重试时为 `needs_review`。缺当前 workspace 模型凭据保持 `waiting_credentials`；不得从其他 workspace 借用。关闭窗口不新增领取，运行中工作按现有安全边界结束或留下需核查状态。
- 队列上限 100 项；满时明确错误，不静默丢弃。取消仅作用于未开始项。队列状态查询、取消和 resume 均要求当前本地会话令牌的原有写入保护；GET 响应不返回秘密或本机路径。不同 workspace 只能看自己的项，调度器仍全局串行。

## 验收与分工

Luna 唯一写入 `src/research_harness/gui/app.py`、`frontend/app.js`，必要 `frontend/i18n.js`/`style.css`、`tests/test_gui_multicontext.py` 和一个新定向队列测试；不改核心、公开 schema、旧 run、冻结资料。Terra 只读初验，Sol 最终验收固定候选和最终包。用两个临时 workspace、可控阻塞/失败与 synthetic host 任务验证排队、取消、幂等、重启、外部文件锁、停止、凭据隔离及 UI 状态；不得调用真实 API/付费模型。若在既定白名单内无法达到必要行为，报告精确阻断，不放宽测试来取得通过。
