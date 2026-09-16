# D19-P3 替代运行验收

运行：`inv-b7b6c9cbba4e`。**本次有界案例验收通过**：科学正文通过 Astra 独立审查，标准导出与重开核验通过。服务的检索覆盖保持 partial，不等于全面检索完成。

阅读入口：[中文技术调查报告](../.local/d19-p3-loop2-replacement/investigation-workspace/reports/inv-b7b6c9cbba4e/run-inv-b7b6c9cbba4e/technical_report.zh-CN.md)、[中文主题综述](../.local/d19-p3-loop2-replacement/investigation-workspace/reports/inv-b7b6c9cbba4e/run-inv-b7b6c9cbba4e/literature_review.zh-CN.md)。同目录保留 canonical、两份 HTML、comparison.csv、human-review.csv 与 bibliography.bib，共 8 个标准导出文件。

## 交付内容

在同一研究问题下，用三篇本地综述与一篇新增开放全文，形成中文技术调查报告和主题综述。正式结果包含 11 条 finding、12 条 claim、9 个正文分节。两个仅含书目条目的本地片段未作为科学结论来源。

主要结论是：阳离子与聚合物主链需要共同考察；芳醚降解、邻近铵基效应和机械性质相互关联；电导率可作为传输性能及浸泡后保持性的指标，但不同碱液、温度、湿度、时长和对象之间不能直接排名。AWE 隔膜的长期测试建议与 AEM 燃料电池机制示例已分开。

## 验收依据

- 实际进程加载指定修复版；OpenAlex 两页候选与唯一首选下载有记录。
- 新全文 34 页经 Docling 解析，独立发现库导入 585 条证据；8 条 RAG 命中通过公共接口接入。
- 分析任务含 48 条事实，6 条本地 baseline 均可正式引用；新旧证据的身份、正文和定位信息独立核对一致。
- 12 条正式 claim 覆盖 3 篇本地文献和 1 篇新增文献；引句均为原证据连续文本，复合主张有对应上下文支持。
- 原 PDF 第 12 页图像确认三组条件分别为 ≤4 M NaOH/80°C、8 M NaOH/120°C、5% RH/100°C，未拼成同一试验。原提取字符保留。
- 综合与正文各经过一次集中科学反馈；正文换行、Markdown 条件表和引用已读回核对。章节引用元数据同步后通过核查角色。

证据位于 `.local/d19-p3-loop2-replacement/astra/`；角色与用量记录位于该目录上一级。原始失败运行和报告保留。

## 实际用量

| 项目 | 实际 / 上限 |
|---|---|
| 来源请求（失败运行 + 替代运行） | 3 + 2 = 5 / 8 |
| 下载尝试 | 1 / 1 |
| 下载 HTTP | 11 / 12 |
| 下载字节 | 7,818,339 / 10,485,760 |
| 服务角色任务（含失败运行 planning） | 1 + 7 = 8 / 8 |
| 宿主生成及修订（执行者逐项台账） | 12 / 12 |

宿主台账计入分析、业务判断、综合和写作各一次答案修订；不将部署脚本修正或既有引用的机械元数据同步算作新的科学答案生成。核查首稿为第 12 次，之后没有再次生成角色答案。

## 本轮修复与边界

部署时发现沙箱安装物的包子目录 ACL 不允许联网执行身份读取。改为由实际执行身份从既有 wheel 离线安装到独立目录，没有修改系统权限。实际模块路径在执行时核对，阻止静默回退旧包。

最后导出遇到真实书目类型 `review` 与 BibTeX 条目类型不一致；只在 BibTeX 输出时映射为 `article`，canonical 保留原始 `review`。相关源码测试 13 项通过，未修改冻结科学结果。

修复后新安装目录为 `loop/engineering/target-host-review`，实际执行身份下的 13 项安装版导出测试通过。正常服务导出 8 个文件，重开读回后结果与 ReportData 相同，canonical 字节相同、预算不变、pending 为零；未调用 resume 或重生成角色。最终原库数量与配置仍为 23 文档、23 版本、8,820 条证据，与起始快照一致。独立最终记录为 `astra/final-acceptance.json`，工程导出记录为 `final-export-selftest.json`。

HTML 沿用现有逐行文本导出方式，Markdown 表格没有转换成原生 HTML table；阅读条件表优先使用 Markdown。本轮未扩展排版引擎。

本例再次命中已知 perspective，证明的是有界流程与证据使用，不代表陌生文献泛化、全面领域检索或原始实验复现。来源候选上限及未下载全文使服务保持 partial；不能据此输出统一材料性能排名。没有扩展 GUI、表格解析、新来源、监测或 GitHub 同步。
