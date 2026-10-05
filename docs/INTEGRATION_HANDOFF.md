# CirootHarness 离线候选交接

2026-10-05。产品编码由 Luna 完成，协调者独立验收。当前交付为离线工程候选，真实模型及来源待激活。

交付目录：`.local/windows-delivery-20261005-final/prepared-delivery/`。
启动：`portable/ResearchHarnessGUI/ResearchHarnessGUI.exe`，保留整个目录；这是免安装版。可选研究环境与三语指南分别位于 `optional-runtime/`、`guides/`，构建清单为 `delivery-manifest.json`。

有效检查：最终 CI 离线回归 331 项通过，前端 79 项及构建通过；两个安装环境共 96 个包内文件与最终 wheel/源码一致；旧库一致性副本升级保留原 12 表、报告与原库哈希。实际 PaperQA 五段冻结摘录完整闭环、六项导出及重开独立通过，实际 STORM 离线接口复现通过；模型均为 mock，外发为零，语义未评判。PaperQA 输出仅引用一段论文，专利引用缺口没有隐藏。

Windows EXE 实际构建及 WebView2 启动通过。后续原生交互受宿主窗口坐标异常阻挡：截图窗口越界，点击坐标超过窗口范围；不能声称原生配置、调查、复核、导出及重开全部通过。

待完成：真实模型与授权 API 激活；KIPRIS、GPSS、Pearl 等缺失规范的确认；Docker 宿主构建与持久化验收；完整原生交互验收；人工科学标注及同预算 RAG 对照。来源 CLI 已集成，GUI/HTTP 来源执行入口尚未交付。Docker 配置需要匹配的完整源码作为构建上下文，本包不包含已构建镜像。

不发布公网，不购买服务，不申请账号。下一步先完成本包原生交互验收，再按明确模型、来源及数值预算激活真实运行。
