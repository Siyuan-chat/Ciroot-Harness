# F04 / U09 当前候选独立验收

日期：2026-09-25。只用命令行、本地 HTTP 和 Edge headless；未改产品代码、未调用模型或研究 API。本轮主技能 software-validation-loop；新增工作区与对话方案按 kiss 复用现有核心。

## 结论

F04 当前回归通过；U09 定向 Python 测试、最终包单命令完成与幂等重放通过。用户发现的“不能新建工作区”属确认存在的产品入口缺口，不属于 F04 选择器修正。新增工作区、后台 agent 控制及 GUI 对话目标见 `GUI_WORKSPACE_AGENT_CHAT_PLAN_20260925.md`，尚未实施。

## 有效检查

- `PYTHONPATH=src`，`.local/d19-runtime/venv/Scripts/python.exe -m pytest tests/test_gui_queue.py tests/test_gui_multicontext.py tests/test_gui_contract.py -q`：**16 passed**，8.92 秒，1 条 AnyIO 弃用警告。仅计这三个文件，不复述其他执行者的 148 项为本轮结果。
- `node --test frontend/api.test.js frontend/i18n.test.js frontend/library-view.test.js`：**8 passed**。
- `frontend/multicontext-check.mjs`：**failures=[]**，包含 F04 控件/持久状态/请求 scope 一致性及既有 U06/U08 回归。证据：`.local/gui-layout-acceptance/current-f04-independent/`。
- 最终包采用 `.local/gui-package/u09-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`。SHA-256：`9e6b1b2983fa6ed691745323513fee8f0c2c903fa6afd47eac53a849949f2982`。包内 29 个项目 Python 模块与源码编译代码对象一致；9 个前端/样例文件在源码/dist/包内一致。
- 隔离工作区实际 EXE 服务：无令牌队列 GET 返回 403；合成 host run `inv-a354bf979b60` 的 advance 持久命令 `9bca247884214f0ba2c0c5b48544534a` 为 completed，页面显示对应 run 与完成状态。重启复跑同幂等键仍为同 run、唯一匹配的 advance 命令；退出码 0、端口关闭。

完整日志：`.local/gui-layout-acceptance/current-queue-independent.log`、`current-node-independent.log`、`current-f04-independent.log`。包证据：`.local/gui-layout-acceptance/current-u09-independent/` 下 `package.json`、`result.json`、`browser.log`、`check.mjs`；临时启动脚本 `current_u09_probe.py` 在其父目录。

验收脚本校准：原交接脚本假定 advance 响应含 command_id；快速完成路径实际返回业务结果，初次结果没有 commandId。该初次记录保存在 prior-result.json，不作为精确命令身份的证据。独立临时副本改为从已认证队列查询唯一匹配 run/advance 的项，再显式读取并核对 command_id/status；最终 result.json 才是有效身份读回。产品行为未因此改动。后续操作合同应写清即时结果与异步 command 两种响应。

## 范围与剩余项更新

U09 已实现，不能继续沿用早先“尚未开发”的结论。重启、取消、凭据/锁隔离、幂等冲突等由本轮定向测试覆盖；真实 EXE 只测单命令与重放，不扩大为付费并发/所有崩溃窗口验收。

G03/G05/G06 的 F04 包离线全流程记录见 `GUI_F04_PACKAGE_OFFLINE_ACCEPTANCE_20260925.md`；本轮未在 U09 包重跑其完整 8 角色、14 下载流程，不把旧包结果升级为新版完整用户流程通过。原生 WebView2 交互本轮未测。

确认尚缺：用户创建工作区、GUI 对话和 agent 执行连接、managed CLI/MCP 共用 GUI 调度；以及此前的 live 调查入口、导入管理、跨库联合检索等后续阶段。现有 standalone CLI/MCP 直接调用核心，不能声称已能驱动 GUI 对话或安全地与其共用调度。

手工体验新版本应打开上述 u09-dist 包，而非最早 `.local/gui-package/dist/` 目录中的旧 EXE；本轮未覆盖或替换旧包。
