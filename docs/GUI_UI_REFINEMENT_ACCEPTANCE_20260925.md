# GUI 界面返工验收（2026-09-25）

最终手工验收包：`.local/gui-package/ciroot-ui-refined-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`。运行时保留整个 `ResearchHarnessGUI` 目录；旧包均保留，不从旧 `dist` 路径启动。

## 本轮范围和结果

- 新建工作区弹窗：名称全宽、说明为可选短文本框、参照文献库单独一行，空库提示一行；主按钮和关闭按钮分层。750×700 实际包页面截图：`.local/gui-layout-acceptance/ciroot-ui-refined/dialog-750.png`。
- 对话位于可收起和重新展开的侧栏；会话列表直接可见，可新建、选择，草稿按会话隔离。窄屏的内容/对话切换保留。1280px 会话列表宽 190px；750px 对话占满视口，不保留空导航列。源码布局证据：`.local/gui-layout-acceptance/f04-scope-fix-20260925/results.json`、`chat-1280x800.png`、`chat-750x700.png`。
- 文献列表保有可读宽度；详情以覆盖抽屉打开，不再形成列表/详情/对话三条窄列。实际包 1280px、750px 均显示 23 条默认库文献，无横向溢出；证据 `.local/gui-layout-acceptance/ciroot-ui-refined/actual-package-result.json`。
- 首次无手动偏好时读取系统/浏览器语言：中文或日文分别对应 zh/ja，其他语言以英语为默认；手动选择优先并保留。英语主要页面和弹窗已扫描，Reader 标签为 `Evidence ID`。原始文献标题按来源语言显示。

## 验证

- `cd frontend; npm run check; npm test; npm run build`：通过，前端测试 34/34。
- 离线 Edge 布局脚本 `frontend/multicontext-check.mjs`：`failures=[]`，覆盖 1440、1280、1024、850、750、390px 与放大字体；证据在 `.local/gui-layout-acceptance/f04-scope-fix-20260925/`。
- PyInstaller 使用 `.local/gui-package/ResearchHarnessGUI_Ciroot_UI.spec` 生成独立包，日志 `.local/gui-package/ciroot-ui-refined-build.log`。包内 `index.html`、`app.js`、`style.css`、`i18n.js`、logo 与 `frontend/dist` 逐文件一致，synthetic investigation 数据包含在包内。
- 实际 EXE 以隔离工作区和 `--no-browser --port 18840` 启动；无头 Edge 在 1280/750px 打开实际页面。标题 `CirootHarness`，文献 23 条，弹窗字段尺寸正常，对话区域可达，页面错误为空；首次发送回读为 `ready`，消息顺序 user、assistant，会话列表 1 项。证据 `.local/gui-layout-acceptance/ciroot-ui-refined/actual-package-result.json`、`first-send.json` 与截图。

未使用 Computer Use、真实研究 API、付费模型或 GitHub 推送。原生 WebView2 交互和任务栏图标仍待用户手工验收；本记录不把无头浏览器检查等同于原生窗口验收。
