# F04 修正与最终包离线流程验收

日期：2026-09-25。依据 `GUI_PACKAGE_ACCEPTANCE_AND_REMAINING_20260925.md`。Luna 单写前端固定候选；Terra 只读复验；Sol 在独立目录构建 EXE 并检查实际服务。旧包及历史 FAIL 记录未覆盖。未用 Computer Use，未调用真实来源或付费模型。

## F04

`frontend/app.js` 的工作区、文献库、分组和语言选择器由当前状态驱动，不作为普通表单草稿恢复。离开 scope 前保存非敏感草稿，进入 scope 后只恢复该 scope 的搜索、筛选和编辑字段。`frontend/multicontext-check.mjs` 加入 DOM 选择值、localStorage 与实际请求头一致性检查，保留 U06 迟到分页和 U08 迟到事件回归。

Luna 自检 `npm test` 7/7、`npm run check`、`npm run build` 和 Edge headless 均通过；Terra 独立复验结果为 `failures=[]`，证据在 `.local/gui-layout-acceptance/terra-f04-independent-20260925/results.json`。Sol 用 `ResearchHarnessGUI.spec` 在 `.local/gui-package/f04-dist/` 构建独立 EXE；9 个前端/合成样例资源在源码、dist、包内逐字节一致。对该 EXE 的真实 HTTP 页面复验 w1/l2→w2/l3→w1 及 c1 分组，控件、存储和请求头一致，证据在 `.local/gui-layout-acceptance/f04-package-final/results.json`。初版临时探针在选择框改变后过早检查请求，结果未通过；加入请求完成等待后才作为最终有效证据。构建日志：`.local/gui-package/f04-build.log`。

本次固定包：`.local/gui-package/f04-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`，SHA-256 为 `62a72ba6ca105c86408a552b18f942593c8715e15d9c5a44c2918da9a1351554`。与历史包分目录，移动或手工使用需复制整个 `ResearchHarnessGUI` 目录。

## G03/G05/G06 最终包离线验收

权威记录为 `.local/gui-layout-acceptance/g03-g05-g06-final/attempt-04/results.json`、同目录 `commands.txt`、`automation.log`、截图和下载文件；前三次为自动化脚本校准记录，不混入通过结论。运行方式是最终 EXE 的 `--no-browser` 本地服务加 Edge headless，隔离临时工作区；`synthetic/host/allow_network=false`，代理陷阱、HF offline 和浏览器非 loopback 拦截启用。

| 项 | 结果 | 可观察证据 |
| --- | --- | --- |
| G03 | **通过，离线合成范围** | 页面创建 `inv-45662111f2d5`，在 UI 提交 8 个角色任务后 `completed`、coverage complete；报告 1 claim/2 evidence，点击主张读回 `paper-001/v1` 的 paragraph 2 原文与 locator。 |
| G05 | **通过，既有 monitor issue 范围** | 隔离工作区预置 synthetic monitor issue；UI 将 `open/uncertain` 判为 `resolved/relevant`，仅一条人工决定事件；普通 run monitor 查询为空，重启后 UI/API 仍读回决定与历史。 |
| G06 | **通过，合成报告范围** | UI 导出并下载 14/14 产物，合计 15,319 bytes；下载字节与服务文件及登记清单一致，canonical ReportData 与 API 事实一致，格式可重开；重启后仍有报告和 14 件产物。 |

Terra 独立核对最终记录、脚本、包时间与进程清理，三项结论一致；测试结束无残留 ResearchHarnessGUI 进程。记录的浏览器外部请求与合成来源外呼均为 0。该验收不证明真实资料的科学质量、真实来源/模型调用、monitor 周期创建或 WebView2 原生窗口内全流程。

U09 持久队列与恢复尚未实现，方案见 `GUI_U09_PERSISTENT_QUEUE_PLAN_20260925.md`。真实资料入口、跨库联合检索、GUI 导入及 G04 长调用停止时序均未随本轮改判。
