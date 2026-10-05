# W2 managed 本机控制通道固定候选验收

日期：2026-09-25。依据 `GUI_W2_EXECUTION_CONTRACT_20260925.md`。Terra 独占后端/CLI/MCP 写入并自检，Luna 随后独占前端通知写入；Sol 在固定候选上独立复验。未重置当前未提交修改。

## 候选与检查

- 后端新增 `src/research_harness/gui/control.py`、`control_mcp.py`，修改 `app.py`、`desktop.py`、`__main__.py`、`pyproject.toml`，新增 `tests/test_gui_control.py`。前端修改 `frontend/app.js`、`api.js`、`api.test.js`、`i18n.js`、`style.css`。
- `PYTHONPATH=src; .local/d19-runtime/venv/Scripts/python.exe -m pytest tests/test_gui_control.py tests/test_gui_workspace_create.py tests/test_gui_queue.py tests/test_gui_multicontext.py tests/test_gui_contract.py -q`：**22 passed**，1 条第三方 AnyIO 弃用警告。`cd frontend; npm test`：**11 passed**；Luna 的 `npm run check`、`npm run build` 通过。
- 源码服务使用 `python -m research_harness.gui --workspace <隔离工作区> --static-dir frontend/dist --port 18781`；Edge headless 脚本 `.local/gui-layout-acceptance/w2-source-final/check.mjs` 返回 `ok=true`。
- 独立包由 `.local/gui-clean-venv/Scripts/python.exe -m PyInstaller --noconfirm --distpath .local/gui-package/w2-dist --workpath .local/gui-package/w2-build .local/gui-package/ResearchHarnessGUI.spec` 构建，日志 `.local/gui-package/w2-build.log`。EXE `.local/gui-package/w2-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`（47,542,583 bytes），须保留整个目录。实际包以 `--no-browser --workspace <隔离目录> --library-workspace <同目录> --port 18782` 启动；`.local/gui-layout-acceptance/w2-package-final/check.mjs` 的最终 `result.json` 为 `ok=true`。第一次脚本在 EXE 服务完成启动前连接，收到 `ERR_CONNECTION_REFUSED`；待 registry 返回 200 后复跑通过，未改产品代码。

## 可观察结果与边界

CLI 通过当前服务私有 descriptor 创建 synthetic host run `inv-4c0eb0714e27`；同一 EXE 页面接收 `view.open` 通知时仍停在“文献库”，用户点击通知后才打开“调查任务”并显示该 run。managed MCP 的本地转发由 Terra 自检覆盖；通用桥测试不等于 Codex/Claude Code 客户端真实对话接通。会话 token 不在命令参数或结果中；测试工作区的强制停止会跳过服务 `finally`，测试后已单独清除该隔离目录的 descriptor/token。

W2 不包含 W3 对话或 W4 外部 agent 双向消息。未调用真实研究 API 或付费模型，未使用 Computer Use，未复验原生 WebView2 交互；本结果不代表完整研究工作台通过。
