# W1 新建工作区固定候选验收

日期：2026-09-25。依据 `GUI_WORKSPACE_AGENT_CHAT_PLAN_20260925.md` 与 `GUI_W1_EXECUTION_CONTRACT_20260925.md`。Terra 独占后端写入并交付，随后 Luna 独占前端写入；Sol 只读检查固定候选、构建独立 EXE 并做实际服务与 Edge headless 验收。原有未提交成果未重置或覆盖。

## 候选与命令

- 后端：`src/research_harness/gui/app.py`、`tests/test_gui_workspace_create.py`。前端：`frontend/app.js`、`frontend/api.js`、`frontend/i18n.js`、`frontend/style.css`、`frontend/api.test.js`、`frontend/i18n.test.js`。
- Python：`$env:PYTHONPATH='src'; .local/d19-runtime/venv/Scripts/python.exe -m pytest tests/test_gui_workspace_create.py tests/test_gui_multicontext.py tests/test_gui_queue.py tests/test_gui_contract.py -q`，**19 passed**，1 条第三方 AnyIO 弃用警告。
- 前端：`cd frontend; npm test`，**10 passed**；Luna 的 `npm run check`、`npm run build` 通过。
- 包：`.local/gui-clean-venv/Scripts/python.exe -m PyInstaller --noconfirm --distpath .local/gui-package/w1-dist --workpath .local/gui-package/w1-build .local/gui-package/ResearchHarnessGUI.spec`，成功；构建日志 `.local/gui-package/w1-build.log`。实际 EXE：`.local/gui-package/w1-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`（47,531,372 bytes）；使用时须保留整个目录。
- 实际包无头浏览器：`node .local/gui-layout-acceptance/w1-package-final/check.mjs`，最终 `result.json` 为 `ok=true`。初次探针在异步空库状态呈现前读取文案，`unindexedVisible=false`；脚本改为等待空态后重测通过，未修改产品代码。

## 可观察结果

从实际 EXE 页面创建 `ws-5af8b7af24424a9d9b3ebf5347c26e0b` 后，工作区选择器立即有新项，当前客户端仍是 `default`；按“创建并进入”后才切到该 ID，页面显示空库未索引。刷新后仍选中新工作区；再次创建同名空间 `ws-7a06202b451d452eb80cb2bc9c6ee845` 获得不同 ID，当前 scope 未被抢占。重启同一 EXE 服务后，`GET /api/v1/registry` 同时返回这两个 ID、`unindexed` 和旧 `default`。后端定向测试覆盖同键重试/冲突、路径拒绝、已有库只读关联及注册保存失败回滚。

本次只验收 W1。本轮未实现 W2 managed 控制、W3 GUI 对话、W4 外部 agent 双向连接；未调用真实研究 API 或付费模型，未使用 Computer Use，未测试原生 WebView2 交互，也不把本结果表述为完整研究工作台通过。
