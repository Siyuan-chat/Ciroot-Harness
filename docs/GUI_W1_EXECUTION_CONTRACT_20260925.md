# W1 新建工作区执行合同

日期：2026-09-25。用户已要求按 `GUI_WORKSPACE_AGENT_CHAT_PLAN_20260925.md` 开发。本阶段只交付 W1；W2 managed CLI/MCP、W3 对话、W4 外部 Agent 待 W1 固定候选验收后顺序推进。保留现有未提交修改，不修改调查核心、冻结资料、旧工作区或旧库内容。

## 接口与数据

- `POST /api/v1/workspaces` 使用现有 `x-session-token` 与 `idempotency-key` 请求头。body 为 `{name, description?, reference_library_ids?}`；名称去首尾空白后 1–80 字，说明至多 500 字，`reference_library_ids` 只允许空数组或一个已注册 library ID。请求不得包含路径。旧用户可见注册仍按原配置加载。
- 服务端生成 `ws-` 开头稳定随机 ID，目录位于传入 GUI 数据根的子目录；空库生成该工作区专属 library ID 和空目录，并明确 `unindexed`。关联已有库仅添加只读关联，不改库目录或索引。`description` 只作为显示元数据。
- 注册持久状态保存在 GUI 数据根，以写入原子性或事务保障。相同幂等键与相同规范化 body 返回同一身份；同键不同 body 返回 409。两次同名新请求可有不同 ID。启动合并可信配置及新增注册，ID 冲突显式报错，不覆盖旧配置。异常不能留下可被列为正常工作区的半成品。
- 回复 `{schema_version:"1",workspace_id,name,description,default_library_id,libraries:[...],status}`，不回传目录。GET registry/workspaces/contexts 使用同一更新后的注册；其他客户端只在自行刷新后看到新项，不能被动切换 scope。
- 前端在工作区选择器旁和空态提供同一个入口。表单输入名称、可选说明、已有参照库或空库；显示“保存于本机应用数据目录”及空库未索引。成功后更新 registry，只有用户选择“创建并进入”时才切到新 scope。三语界面有明确文案，用户内容不翻译。

## 分工与验收

Terra 先独占写入 `src/research_harness/gui/app.py` 和新增 `tests/test_gui_workspace_create.py`，自测交固定候选；期间 Luna 不修改产品代码。Sol 再交 Luna 独占写入 `frontend/app.js`、`frontend/api.js`、必要 `frontend/i18n.js`/`frontend/style.css` 与受影响前端测试。共享文件如有需要只由当前阶段写入者负责。Sol 最终独立验收并记录，必要时仅将一个合并反馈交给当前写入者。

离线验收必须观察两个同名工作区、幂等重试/冲突、空库进入并显示未索引、关联旧库只读、重启仍在、原工作区及原库不变、浏览器/模型无法提交磁盘路径。检查真实 HTTP/UI 与最终包；不调用真实研究 API 或付费模型，不使用 Computer Use，不推送 GitHub。
