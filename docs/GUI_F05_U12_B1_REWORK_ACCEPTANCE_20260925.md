# GUI F05 / U12 / B1 修正验收

日期：2026-09-25。最终候选为 `.local/gui-package/ciroot-message-final-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`。运行时须保留整个 `ResearchHarnessGUI` 目录。

## 结论

- 选中文献库后，内容区直接显示该库文献列表。最终 EXE 的默认库在 1440px 和 850px 页面均显示 23 条；窄屏从对话切回内容、重新选库后仍显示 23 条，对话草稿保留。实际页面证据：`.local/gui-layout-acceptance/ciroot-message-final/result.json`、`desktop-library.png`、`narrow-library.png`、`narrow-chat.png`。
- F05 首次直接发送通过：实际 EXE 页面依次发出 `POST /api/v1/conversations` 和同一会话的 `POST .../turns`，均返回 200；消息顺序为 user、assistant，规划阶段 run 数量为 0。显式执行后的独立回读为 `completed`，run_id 为 `inv-876b1b4b02c1`，证据 `completed-readback.json`。执行探针的即时 `execute-result.json` 曾过早读取为 ready，保留作探针时序问题记录，不作为最终状态证据。
- U12 精简常驻文字和面板；窄屏使用内容/对话切换，选库与进入文献库导航会回到文献列表。范围、预算、技术细节由用户在对话中询问 Agent。离线 Edge 的 4 种视口、三语及 125%/150% 字体检查由实现与只读复验完成；最终 EXE 的宽窄截图见上述目录。
- B1 页面标题、logo、配色及打包图标采用 CirootHarness。EXE 技术文件名仍为 `ResearchHarnessGUI.exe`。本轮以无头浏览器验证实际包页面，未将原生 WebView2 操作或任务栏图标列为已手工通过。

## 命令与结果

- `cd frontend; npm test`：29 passed；`npm run check`、`npm run build`：通过。
- `$env:PYTHONPATH='src'; .local/d19-runtime/venv/Scripts/python.exe -m pytest tests/test_gui_api_conversation.py tests/test_gui_conversation.py tests/test_gui_contract.py tests/test_gui_control.py tests/test_gui_external_executor.py tests/test_gui_model_credentials.py tests/test_gui_multicontext.py tests/test_gui_packaging.py tests/test_gui_queue.py tests/test_gui_workspace_create.py -q`：最终候选源码 39 passed、1 条第三方弃用警告。
- 最终 EXE：`ResearchHarnessGUI.exe --no-browser --workspace <隔离目录> --port 18832`；无头 Edge 脚本 `.local/gui-layout-acceptance/ciroot-message-final/check.mjs`，`result.json` 的 `ok=true`、23 条列表、首次发送与草稿保留均来自实际包。隔离工作区为 `.local/gui-layout-acceptance/ciroot-message-final/workspace`。
- 打包日志：`.local/gui-package/ciroot-message-final-build.log`。本地 Ciroot spec 构建后，把三个 synthetic investigation JSON 放入 `_internal/research_harness/examples/investigation`；正式构建脚本 `packaging/build_windows.ps1` 已加入同一数据目录。既有配置文本和历史包均保留。

动态帮助与 API 上下文只用本地假 provider 复验；没有真实研究 API、付费模型、Computer Use 或 GitHub 推送。此结论只覆盖本轮 GUI 修正，不表示完整研究工作台或原生 WebView2 交互通过。
