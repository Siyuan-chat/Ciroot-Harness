# 工作区与对话 Agent：固定候选离线验收

日期：2026-09-25。依据 `GUI_WORKSPACE_AGENT_CHAT_PLAN_20260925.md`，按 W1→W2→W3→W4 顺序实施；Terra 与 Luna 顺序独占各自交付，不曾同时写产品代码。Sol 复验固定候选。保留原有未提交修改、旧包和历史验收记录；未推送 GitHub、未使用 Computer Use、未调用真实研究 API 或付费模型。

## 交付与命令

| 阶段 | 本轮可观察结果 | 证据 |
| --- | --- | --- |
| W1 | GUI 创建同名不同 ID 的工作区；只在“创建并进入”后切 scope；空库显示未索引；重启后注册仍在 | `GUI_W1_ACCEPTANCE_20260925.md`、`.local/gui-layout-acceptance/w1-package-final/result.json` |
| W2 | CLI 创建的 run 在同一 GUI 服务可见；后台导航只提示，用户点击后才打开；managed 控制经 U09 队列/作用域 | `GUI_W2_ACCEPTANCE_20260925.md`、`.local/gui-layout-acceptance/w2-package-final/result.json` |
| W3 scripted | 850×600 Edge 中输入文字、收到已校验的 synthetic 规格；文字 turn 不建 run，点击显式执行后创建并完成 run、显示报告入口；发送后输入清空 | `.local/gui-layout-acceptance/w3-source-final2/result.json`、`850x600.png` |
| W4 本地桥 | 最终包中 external GUI turn → managed bridge 领取 → W2 受控 `run.create` → 进展/回复/ack 回同一 conversation；切换 API 后原消息仍在 | `.local/gui-layout-acceptance/agent-chat-final/external-result.json`、`external-850x600.png` |
| API 规划无凭据 | 最终包页面显示 `waiting_credentials` 和 UNKNOWN 用量，执行按钮不出现，run 数为 0，浏览器外部请求为 0 | `.local/gui-layout-acceptance/agent-chat-final/api-result.json`、`api-850x600.png` |

Sol 执行 `$env:PYTHONPATH='src'; .local/d19-runtime/venv/Scripts/python.exe -m pytest <tests/test_gui_*.py 全集> -q`：**33 passed**，1 条第三方 AnyIO 弃用警告；`cd frontend; npm test`：**23 passed**，`npm run check` 与 `npm run build` 成功。后端 API 规划的成功、缺凭据、预算、scope 扩大、未知调用重试/重启使用 fake HTTP，未发送真实请求。

最终独立包由 `.local/gui-clean-venv/Scripts/python.exe -m PyInstaller --noconfirm --distpath .local/gui-package/agent-chat-final-dist --workpath .local/gui-package/agent-chat-final-build .local/gui-package/ResearchHarnessGUI.spec` 构建；日志 `.local/gui-package/agent-chat-final-build.log`。EXE 为 `.local/gui-package/agent-chat-final-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`，须连同整个目录使用。最终包以隔离工作区和 `--no-browser --port 18787` 启动；9 个前端/合成样例资源与 `frontend/dist` 逐字节一致。

真实 MCP STDIO 层还使用 `.local/gui-layout-acceptance/w4-package-final/mcp_stdio_check.py` 经 `mcp.client.stdio_client` 执行 `initialize/list_tools/call_tool`：工具 `control` 可调用、`workspace.list` 返回默认工作区。该检查曾暴露 MCP SDK 2.x 与旧 `FastMCP` 的兼容问题，已在 `control_mcp.py` 修复；最终检查通过。第一次脚本因测试端未传 PYTHONPATH、第二次因测试端误用 `isError` 属性失败，校正后才计入有效结论。包启动后的少数初始浏览器探针在服务完全可用前出现连接错误；等 registry 可读并重跑后的结果作为有效记录。W4 执行器切换验收还发现摘要响应导致前端暂时丢消息，已修复为成功切换后按原 scope 读回完整会话；最终包复验 `ok=true`。

## 边界

W3 scripted 仅是已验证合成夹具，不能作为真实资料研究结论。API 对话规划代码与前端配置已实现，但真实 provider 连接、模型输出质量和收费预算实际结算**未验收**。W4 验收到本地 managed MCP 桥与通用 STDIO 客户端；Codex/Claude Code 实际客户端接收 GUI 消息并回复**未验收**，界面仅提示需连接/领取。原生 WebView2 窗口交互、真实资料入口、GUI 文献导入和跨库联合检索仍未随本轮改判；不能称完整研究工作台通过。
