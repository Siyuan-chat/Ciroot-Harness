# Windows GUI 打包候选独立复验

日期：2026-09-24。结论：**不通过整体验收；阻断项为筛选后的文献身份错配。** 本轮只验收与记录，没有修复产品、调用研究模型或新增来源调查。

## 候选与检查边界

- 用户指定 EXE 的实际路径：`.local/gui-package/dist/ResearchHarnessGUI/ResearchHarnessGUI.exe`（用户消息中的用户名转义按当前项目实际目录解析）。
- EXE SHA-256：`51640AA23AEF73BA54493B0EC2FC73C17BEBF715624623B80ABD216E68F4FA1F`，与 GUI_ACCEPTANCE.md 最新原生窗口候选一致。
- 打包 `_internal/frontend/dist/app.js` 与当前 `frontend/app.js` SHA-256 均为 `AAA7969878D0D641BEB711A8E640C1931FE977AC5906F2509ABE8E47B7A75F33`；下述源码根因对应实际打包文件。
- 原生 UI 实际读取到 `Patent Agent` WebView2 窗口，窗口页面为本机 loopback 60117；只做浏览、筛选、详情与入口操作，未在该默认工作区提交调查或人工决定。
- 另外从同一 EXE 启动 `.local/gui-independent-acceptance` 隔离工作区，loopback 64071 用于服务与本地检索检查；只读既有参照库。启动日志保留在该目录 `desktop.log`。
- 早期隐藏启动及窗口发现曾未返回可操作窗口，后续已取得真实窗口，因此不将这次工具启动现象认定为产品启动缺陷。
- 已读 DECISIONS.md 后续记录：用户批准改为借鉴交互、不复制 Zotero 源码，并增加原生窗口与 RAG 检索。按最新授权验收，不用旧源码复用选择否定当前实现。

## 必须修复：F01 / P1 文献筛选后详情与原件串项

原生窗口复现步骤：

1. 打开文献库，显示 23 篇。
2. 在顶部搜索框输入 `Tuning Alkaline`。
3. 中央只剩 `Tuning Alkaline Anion Exchange Membranes through Crosslinking: A Review of Synthetic Strategies and Property Relationships`，document_id 为 `doc-a2bff6c31ccf20278f3276cc`。
4. 点击该卡片“查看详情”。
5. 右侧却显示 `A Brief Review of Poly(Vinyl Alcohol)-Based Anion Exchange Membranes for Alkaline Fuel Cells`，document_id 为 `doc-972410c75d86de8bb3b803fb`，原件地址也指向后者 `/versions/ver-0384031f0aa9f7ca4a5d4fdb/file`。

预期：卡片、详情、版本与原件都对应所选文献。实际：筛选后第一个卡片选择了未筛选数组第一项。用户可能阅读或引用错误原文，故为整体验收阻断。

根因已由打包对应源码确认：`content()` 将过滤后的数组传给 `cards()`；`cards()` 使用过滤数组的索引生成 `data-select="document:0"`；`select()` 却用此索引访问完整 `state.library`。同样风险适用于改变列表位置的类型筛选。

交给 Luna 的修正要求：通过稳定 document_id 绑定选择，或明确保持显示集合到源对象的映射；同时核对过滤、追加分页、清空过滤后的选择身份。不要只对本条标题特殊处理。新增有意义的 UI/行为回归：选择原列表末项经筛选成为第一项时，详情与原件 ID 仍相同。重新构建与打包后，Sol 在新 EXE 复验同一操作。

## 其他发现与未完成观察

### F02 / P2 调查创建仍为开发者 JSON 表单

原生窗口点击调查任务→新建离线调查，只提供空的 ResearchSpec JSON、Runtime JSON 文本区，未提供字段引导或已验证样例加载。角色处理源码亦要求手工填写 output_schema 对应 JSON。顶栏 Ask Agent 明确禁用，后端 capability `api_auto_advance=false`。

这不是“付费 API 验收失败”，本轮未授权此类调用；它表明当前可交付层次仍偏向工程调试前端，尚不能证明研究人员通过完整 GUI 独立走完目标流程。建议在原离线范围内提供结构化创建/样例入口及任务操作引导，再完成 G03 浏览器闭环；真实模型执行另按预算验收，不要求本轮直接启用付费功能。

### F03 / P2 筛选结果计数表达不准确

`Tuning Alkaline` 筛选后只有一张卡片，计数仍为 `23 项`，未注明是库总数。源码使用 `state.library.length` 而非过滤结果数。改为“1 个匹配 / 已载入 23 项”，有分页时不要把已加载量称为全库总量。

### 未完成：PDF 原生可见性与完整 GUI 流程

本轮尝试点击服务签发的“打开原件”，未获得可确认的 PDF 页呈现；窗口仍可恢复到原工作台，未据此确定根因。不能将原件地址存在或 HTTP 返回成功当作 PDF 阅读通过。需要在目标 WebView2 中明确验证新窗口/外部浏览器路由和指定页可见性。

当前默认 GUI 工作区没有既有调查运行，未将冻结库直接作为可写工作区接入。G02 完整报告→证据→原件、G03 原生窗口全角色闭环、G04 长任务停止/恢复、G05 原生人工处理、G06 下载后重开以及 G08 指定窗口尺寸/键盘流程仍待补验。本轮不把旧报告中的部分通过升级为通过。

## 本轮有效通过项

| 检查 | 证据及可声称范围 |
| --- | --- |
| 原生基础界面 | 真实 WebView2 `Patent Agent` 窗口；中文三栏、23 篇列表、筛选与调查入口可操作 |
| 打包服务能力 | 隔离工作区 EXE `/api/v1/capabilities` 返回成功；模型 online=not_checked，api_auto_advance=false，状态如实呈现 |
| 本地向量检索 | 同 EXE `/api/v1/library/search?q=alkaline%20stability&top_k=3` 返回 3 条，mode=hybrid，lexical_hits=1829，vector_hits=8820，模型 multilingual-e5-small；这是接口层检索通过，不是 UI 点击检索全流程通过 |
| 后端针对性回归 | `tests/test_gui_contract.py tests/test_investigation_model_api.py`：17 passed，1 条依赖弃用 warning；日志 `.local/gui-independent-acceptance/contract-tests.log` |
| 前端已有测试 | `node --test frontend/api.test.js frontend/i18n.test.js`：4 passed；只覆盖 API 请求/事件 URL/语言文本，未覆盖筛选后的选择行为 |

检索返回 evidence_id：`ev-81065fa9b74b980d6f1744ac`、`ev-40f532a9fb6ebed569b2981e`、`ev-64e3557da398662139634b23`。不据诊断命中数推断科学召回率。

## 交回开发任务的集中修正

1. Luna 先修 F01 与 F03，提交固定前端候选和选择身份行为测试；不改科学数据或后端证据身份。
2. Luna/Terra 确认 PDF 打开路由，只有确定故障层后由对应单写者修；以原生可见指定页为验收。
3. Sol 将 F02 与剩余 G02–G08 作为实际完成度缺口，按已批准范围补齐；离线可做部分不需要新研究调用。
4. 新候选重新打包，记录最终 EXE 及前端产物身份；独立复验受影响行为。已有后端检查无变更时复用，不反复重跑全仓。

当前状态：基础桌面壳与本地 RAG 接口可用；GUI 整体未通过，等待固定修正候选。
