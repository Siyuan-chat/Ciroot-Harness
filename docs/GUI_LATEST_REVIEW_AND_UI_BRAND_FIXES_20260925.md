# 最新 W1–W4 包独立验收与 UI/品牌修正

日期：2026-09-25。依据用户最新说明，本轮仅验收 W1–W4 及固定侧栏/帮助库增补。L1 导入管理、R1 真实调查入口、X1 跨库检索、D1–D4 最终交付属于后续阶段，不算本轮缺陷。用户新增要求：界面简洁、最新 agent 名称与 logo、全局配色与 logo 一致。

## 结论

**本候选不予完整放行：存在首次发送对话失败的 P1 缺陷；界面简洁性和品牌一致性也未满足用户要求。** 源码测试、包一致性、新建工作区、三语基本布局、帮助检索和多上下文回归通过，不能据此覆盖真实页面上的发送失败。

本轮未改产品代码，未使用 Computer Use，未调用真实模型或研究 API。临时验收数据/脚本保存在 `.local/gui-layout-acceptance/`；所有由本轮启动的 EXE 已正常退出。

## 候选与通过证据

- 包：`.local/gui-package/sidebar-help-chat-dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`，SHA-256 `c490026b72eb32ff6ff6c4e38be94e3b191ce743cb5d93233d9d9528c15c1576`。
- 全部 `tests/test_gui_*.py` 在 d19-runtime、`PYTHONPATH=src` 下运行：36 passed，23.44 秒，仅 1 条 AnyIO 弃用警告。日志 `latest-independent-python.log`。
- 前端 npm test：26 passed；npm run check 通过。日志 `latest-independent-node.log`、`latest-independent-jscheck.log`。
- 提取包内代码，与当前源码比较：34 个项目 Python 模块一致；9 个前端/样例资源源码/dist/包内一致；4 篇帮助 Markdown 与包内一致。证据 `latest-independent-package/package.json`。
- 原仓库 `frontend/multicontext-check.mjs` 原样复跑，`failures=[]`；证据 `latest-independent-multicontext/results.json`，包括 F04/U06/U08。
- 实际包页面：创建并进入空工作区成功；1420×800 与 850×600 的对话侧栏和新建入口可见；中英日切换没有页面横向溢出，输入框右边界在视口内。help.search 命中 `help/workspace_empty_library_skill.md#1`，help.read 返回同一来源原文。
- 实际服务退出码 0，端口关闭。未复验 WebView2 内部控件、真实 provider 或 Codex/Claude 客户端双向往返。

## F05 / P1：首次发送对话被创建响应合同阻断

复现：全新隔离工作区，打开最终 EXE 的实际 HTTP 页面；在默认 scripted 对话输入非空问题，直接点击“发送”。服务端 `POST /api/v1/conversations` 返回 200，并创建 awaiting_input 会话；之后没有 POST turns，页面显示 `RH_GUI_CONNECTION`，消息没有进入会话，执行按钮不出现。

独立最小探针不依赖原交接脚本，证据为 `latest-chat-diagnostic/result.json`、`after-send.png`。创建响应中 conversation_id 位于顶层；GET 单会话才返回 `{conversation: ...}`。

源码原因：`src/research_harness/gui/app.py` 的 create_conversation 返回 `pack(conversation_db().create(...))`（约 902 行）。`frontend/app.js` 的 bindConversation（约 202 行）在首次发送分支读取 `created.conversation`，随后访问其 conversation_id；“新建会话”按钮同样读取 `data.conversation.conversation_id`。两端创建响应结构不一致；前端把这类异常显示为连接错误，实际服务并未断开。新建按钮路径有相同静态缺陷，本轮动态复现的是直接首次发送。

修正要求：Sol 冻结创建接口响应合同，由一个写入者修正/归一化所有调用方；新建、首次直接发送、三种 executor、幂等重放都按真实响应测试。不要只给 fixture 补一个 conversation 包装让测试通过。保留首条草稿与稳定 request_id，失败后可恢复，不能重复建会话/重复提交或丢消息。

验收：新进程+空客户端存储中，不先手工新建会话也能发送；观察真实 POST create→POST turns，同一 conversation 内出现原用户消息与答复；scripted 显式执行后完整完成，规划阶段不建 run。另测“新建会话→发送”、API 缺凭据、external 等待与重试；不调用收费服务也能完成这些接口验收。

探针校准记录：attempt-01 缺少 managed control actor/request_id，attempt-02/03 使用错误提交按钮选择器，不作为产品失败证据。改用实际默认 submit button 后出现等待执行按钮超时；随后最小网络/DOM 探针确认上述响应合同缺陷。`latest-chat-diagnostic/package.json` 中 browser_exit=0 只表示诊断采集结束，不表示对话通过；result.json 的 executeCount=0、错误页面与请求记录才是结论依据。

## U12 / P2：界面拥挤，简洁性未通过

用户手工反馈与本轮截图一致。850×600 顶栏占约 153px，左导航约 150px、对话约 280px，同时保留主内容与下置检查器；初始空页仍重复展示品牌眉题、页面标题、对象检查器和“详情”。输入区长期显示 executor 技术说明，中央工作区被显著压缩。原布局断言“没有横向溢出/侧栏不与 main 相交”不能证明界面简洁可用。

修正方案：

- 宽屏保留固定对话列；对象检查器默认收起，选中对象时按需展开，避免导航+主区+检查器+对话四块常驻争宽。
- 窄屏提供明确的“内容 / 对话”切换或可展开抽屉，保留对话草稿与任务状态；不强求所有面板同时显示。用户仍可随时到达固定对话入口。
- 顶部合并工作区/库/分组到紧凑的上下文区域；新建为邻近入口，语言/设置等低频项收纳，主要动作保持明确。移除无信息价值的重复眉题。
- 对话默认展示消息、输入和发送；executor 用紧凑选择器，模型/预算/技术说明放可展开配置，等待原因出现时再展示。合成模式标识保留，不能为简洁而隐藏关键语义。
- 未选中对象不常驻空详情；底栏默认摘要，可展开 route；partial、等待/失败和当前任务仍清晰可见。

验收：1440×900、1280×800、1024×768、850×600，三语与 125%/150% 字体放大；输入、发送、停止及主要任务操作不被遮挡；键盘能到达；展开/切换不丢草稿和选择。除几何断言外，提供同一场景前后截图并按信息层级与主任务可用面积审阅。

## B1 / P2：CirootHarness 名称、Logo 与配色统一

本机最新权威素材为 `assets/ciroot-harness-logo.png`，图中文字为 **CirootHarness**。保留原图与比例，不重新生成品牌标志。用户要求加入最新名称/logo，与本素材一致。

当前未通过：GUI 仍显示 Patent Agent、P 方块、PATENT RESEARCH WORKSPACE/PATENT INSPECTOR；原生窗口标题仍是 Patent Agent，页面标题为 Research Harness。当前亮蓝色按钮与旧品牌视觉尚未统一到新 logo。

建议色板以 logo 中不透明像素主色为依据：深海军蓝约 `#001F48`、青绿约 `#017675`；它们为栅格统计得到的设计起点，不是假定已有品牌规范。海军蓝用于品牌与主要文字，青绿用于主操作/选中态，背景使用浅中性色；hover/focus/disabled 从同一组 tokens 派生。错误、警告、成功保留可辨的语义色和文字，不能全部改为品牌色。逐项验证文字和焦点可读性。

交付：GUI 顶部 logo/名称、HTML title、原生窗口标题、应用/任务栏图标及关于页一致；源码/dist/最终包实际包含相同资源。小图标从原 logo 的图形部分制定受控派生版本，保留原始素材，避免把整个横版字标压成方形。三语 UI 保持品牌拼写，功能文字本地化。

内部稳定 ID、数据库、旧目录和已有 run 不因更名而改变。EXE 文件名/快捷方式若调整，由 Sol 明确兼容与迁移方式；首版可保留旧技术文件名并在交付说明注明。后续 D2 三语 README/使用说明、D3/D4 发布材料沿用同一品牌，不能提前声称最终发布阶段已完成。

## 给 Sol 的一次性修正任务

本次只收口 **F05 + U12 + B1**，不扩围 L1/R1/X1。先修创建响应合同，再做布局简化和 CirootHarness 品牌统一。Sol 冻结合同与文件所有权，Luna 单写前端/视觉，后端合同如需改由指定单一写入者处理，禁止共享文件并发修改。沿用用户指定的模型与协作方式，本验收对话不启动开发代理。

固定候选交付：修正源码、同版 dist/完整 EXE 包、真实 EXE 的首次发送回归、三语多尺寸截图/可操作性结果、logo/标题/图标核对、已知未测边界。Sol 再独立验收。W3 当前只能记“后端离线能力已有，最新 GUI 首次发送阻断”；W4 的实际外部客户端验收继续待定。
