# GUI 固定侧栏与内置帮助库：独立验收

日期：2026-09-25。用户指出原 EXE 看不到新建入口，要求固定的 LLM 侧栏、可供 LLM 检索的使用说明、内置 system prompt 与若干技能。保留原有未提交修改；本轮未调用真实研究 API、付费模型、Computer Use，未推送 GitHub。

## 最终候选

- EXE：`.local/gui-package/sidebar-help-chat-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`；使用时保留整个 `ResearchHarnessGUI` 目录。
- 顶栏始终提供“＋ 新建工作区”；对话默认展开并占用右侧固定列，顶部“对话 Agent”跳转到该列；窄窗口仍可到达输入区。
- 新建工作区可选择创建未索引空库或只读关联现有库。GUI 仍未提供把 PDF 导入空库并建立文献索引的完整流程。
- 内置帮助资料位于 `src/research_harness/gui/help/`，包括 GUI 使用、创建工作区与空库、受控调查与证据、外部 Agent 交接。独立于研究文献库；`help.search` / `help.read` 返回文档段落和稳定来源。
- API 对话使用内置 system prompt 和有界同会话历史；使用方法问题可返回带帮助来源的自然语言答复，研究问题可形成受本地校验的计划。只有显式执行才创建 run。外部 managed MCP 提示先检索帮助资料，但宿主客户端仍需实际连接和领取 GUI 消息。

## 命令与结果

| 检查 | 命令/方法 | 结果 |
| --- | --- | --- |
| 前端 | `cd frontend; npm test; npm run check; npm run build` | 26 passed；检查和构建通过 |
| GUI 后端 | `$env:PYTHONPATH=(Resolve-Path 'src').Path; $tests=Get-ChildItem tests -Filter 'test_gui_*.py' \| % FullName; & '.local/d19-installed/venv/Scripts/python.exe' -m pytest @tests -q` | 36 passed，1 条第三方 AnyIO 弃用警告 |
| 包构建 | `& '.local/gui-clean-venv/Scripts/python.exe' -m PyInstaller --noconfirm --distpath '.local/gui-package/sidebar-help-chat-dist' --workpath '.local/gui-package/fixed-sidebar-help-final-build' '.local/gui-package/ResearchHarnessGUI.spec'` | 成功；EXE 47,582,799 bytes；4 篇帮助 Markdown 已随包 |
| EXE 页面 | 启动最终 EXE `--no-browser --workspace <隔离目录> --port 18831`，以 Edge 无头浏览器运行 `.local/gui-layout-acceptance/fixed-sidebar-help/check.mjs` | `result.json` 为 `ok: true`；1420×800 和 850×600 顶栏入口、固定侧栏可见且不遮挡中央页面；实际创建并进入空工作区成功 |
| 包内帮助 | 对最终 EXE 的 managed control 调用 `help.search`，问题为“怎么在GUI新建文献库”；再调用 `help.read` | 命中 `help/workspace_empty_library_skill.md#1`，并成功读取同一完整段落 |

页面证据：`.local/gui-layout-acceptance/fixed-sidebar-help/result.json`、`desktop.png`、`narrow.png`、`create-dialog.png`。完整构建日志：`.local/gui-package/sidebar-help-chat-build.log`。

## 验收边界

本轮 UI 使用最终 EXE 本地 HTTP 页面与 Edge 无头浏览器验收；原生 WebView2 手工窗口仍待用户验收。API 模型路径使用 fake HTTP 测试，未发送付费请求，因此真实服务商响应格式和答复质量仍待小预算单独验收。外部 Agent 的 managed 桥和通用 MCP 协议此前已验收，真实 Codex/Claude 客户端自动往返仍未验收。帮助检索是内置文档的确定性段落检索，不属于研究证据库，也不代表完整研究工作台已通过。
