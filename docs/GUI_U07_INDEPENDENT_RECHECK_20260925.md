# GUI / U07 命令行独立复验

日期：2026-09-25。范围：当前工作区源码、离线 API 测试和 Edge headless 回归；未修改产品代码，未使用 Computer Use，未调用外部研究服务或付费模型。

## 结论

本轮检查通过，未发现新的阻断问题。U07 选定文献库证据进入核心输入的离线链路通过；多语言与多上下文的既有自动化回归通过。此结论不等于原生 EXE 整体验收或真实科研工作流验收。

## 有效证据

- `tests/test_gui_multicontext.py`、`tests/test_gui_contract.py`、`tests/test_investigation_query_loop.py`：18 passed，20.93 秒；仅 Starlette/AnyIO 弃用警告。日志：`.local/gui-layout-acceptance/u07-independent-recheck.log`。
- `node --test frontend/api.test.js frontend/i18n.test.js frontend/library-view.test.js`：7 passed。
- `frontend/multicontext-check.mjs`：Edge headless 退出码 0，`failures=[]`。完整结果、截图：`.local/gui-layout-acceptance/u07-independent-headless/`；日志：`.local/gui-layout-acceptance/u07-independent-headless.log`。
- headless 覆盖中英日切换、原文标题保护、草稿/焦点/展开状态保留、视口与字体放大下的页面宽度及底栏边界、动态英文文案、多库/工作区切换、迟到响应隔离。U08 最终任务和底栏仍为 run-b / current-B。
- 阅读确认 `frontend/app.js` 的 `newRun()` 在库索引 ready 时传入 reference scope，`frontend/api.js` 将其写入请求体；服务端冻结版本并传入核心。API 测试验证同 document_id 跨库版本隔离、旧 run 冻结、空分组缺口；核心测试验证不匹配版本拒绝。

## 边界与下一步

布局检查为 DOM 几何及断言覆盖，不替代全部页面的视觉审阅；本轮未执行原生 WebView2 交互。EXE 修改时间为 11:20:14，晚于 GUI 服务 11:07:44 和核心 11:04:09，但时间戳不能证明包内版本一致或原生行为通过。

下一步先固定候选并完成打包内容一致性和原生启动/关闭、选库创建任务的最小冒烟验收。U09 持久队列与重启恢复、U11 原生窗口交互仍单独保留；真实资料及付费模型运行另按既定授权和预算执行，不随本轮自动放行。
