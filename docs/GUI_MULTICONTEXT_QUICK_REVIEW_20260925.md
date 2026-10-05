# GUI 多上下文快速独立复验

2026-09-25。输入：GUI_MULTICONTEXT_EXECUTION_20260925.md 与当前固定候选。仅命令行/Edge headless，没有 Computer Use、产品修改、研究 API 或收费调用。

结论：**本地 GUI 三语、布局与多上下文封装可按有限范围接受；全产品未通过。交接的未完成边界基本准确，但仓库验收脚本尚未包含其声称的 U08 等待修正。**

## 本轮复跑

- 前端 `api.test.js / i18n.test.js / library-view.test.js`：7/7 通过。
- Python `test_gui_multicontext.py / test_gui_contract.py`：12/12 通过，1 条依赖弃用警告。本轮没有复跑额外的 credential 测试，不把交接中的 14 项写成本轮实测。
- app.js、api.js、i18n.js、library-view.js、style.css 五个文件在源码、dist 与 EXE onedir 内资源逐字节一致。没有重新启动 EXE，因此此项仅证明静态候选一致。
- 仓库 `frontend/multicontext-check.mjs` 原样复跑出现 `U08 route target=No run selected`。它等待 B 的 events 请求发出后即读取 DOM，没有等待 B 状态显示。
- 临时副本仅增加“等待 page-status 包含 run-b”，再等待 1200 ms，让 A 的 900 ms 延迟事件返回后检查 B 不被覆盖；其余检查保留，结果 `failures=[]`。产品代码与仓库测试脚本均未修改。

证据：原样运行日志 `.local/gui-layout-acceptance/multicontext/quick-review.log`；有界等待后的结果 `.local/gui-layout-acceptance/multicontext-quick-review/results.json`；临时脚本 `.local/gui-layout-acceptance/quick-review.mjs`。原样脚本会覆写其默认 results.json，当前默认文件是本轮原样失败记录，不应再引用为 failures=[]；应引用以上独立复验路径。

## 需交回 Sol 收口

1. 将 U08 对异步结果的等待真正落实到仓库脚本，并保留“旧任务迟到响应已经到达后仍为 B”的断言。当前是可复现测试问题，不据此认定产品串任务。
2. 保留 U07 未通过完整研究输入闭环：app.py 创建调查仍将原 spec/runtime/scenario 传给核心，选库快照另存 run_references；GUI 快照不等于核心已使用选定参照证据。
3. U09 是排他写入/忙碌提示，尚无持久队列与重启后继续排队验收；不要称为多任务自动调度完成。
4. U11 继续标原生 WebView2 交互未复验；本轮 headless fixture 不替代 EXE 原生交互。

本轮快速复验没有覆盖全部页面、真实多库检索质量或全部异常组合。可接受的是当前已测 GUI 封装边界；下一阶段研究闭环、队列恢复需按现有授权约定另行安排。

## U08 脚本收口与独立复验（2026-09-25）

固定候选仅修改 `frontend/multicontext-check.mjs`。B 的 `/events` 返回 HTTP 200 后，脚本等待页面实际显示 `run-b`；随后等待 A 的延迟 `/events` 返回 HTTP 200，再读取页面任务、底部 route、等待原因和阶段。A/B fixture 分别使用 `source/stale-A` 与 `analysis/current-B`，可辨认串项。新脚本默认写到 `.local/gui-layout-acceptance/multicontext-u08-rerun/`，不会覆盖上述历史失败记录；本次独立复验写到 `.local/gui-layout-acceptance/terra-u08-independent-20260925/`。

实际命令（仓库根目录，PowerShell）：

```powershell
Push-Location frontend
npm test
npm run check
Pop-Location
$env:PLAYWRIGHT_MODULE='C:/Users/Siyuan_ye/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs'
$env:EDGE_EXECUTABLE='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
$env:MULTICONTEXT_OUTPUT_DIR='.local/gui-layout-acceptance/terra-u08-independent-20260925'
node frontend/multicontext-check.mjs
```

Terra 独立只读复验：前端测试 7/7、语法检查通过；无头浏览器退出码 0，`results.json` 的 `failures=[]`。A 的迟到响应返回后，记录仍为 `pageStatus=Run run-b`、`route=ID：run-b Waiting: current-B`、底栏 `Evidence analysis · running`。证据与截图位于 `.local/gui-layout-acceptance/terra-u08-independent-20260925/`。这是测试等待条件的修正，未发现产品串任务缺陷。

Terra 还核对 `app.js`、`api.js`、`i18n.js`、`library-view.js`、`style.css` 在源码、`frontend/dist/` 和最终 onedir EXE 内的资源内容一致。本轮只修改测试脚本，未重打包。U07 仍未完成选库证据进入调查核心；U09 仅排他写入与忙碌提示通过，持久队列和恢复未完成；U11 原生 WebView2 交互未复验。本次 U08 通过不代表完整研究工作台通过。U07 后续方案见 `GUI_U07_NEXT_STAGE_PLAN_20260925.md`，尚未授权实施。
