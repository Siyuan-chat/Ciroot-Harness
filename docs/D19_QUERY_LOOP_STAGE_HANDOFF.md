# D19 单 run 双全文阶段交接与下一步

日期：2026-09-24。状态：**核心双全文证据链已独立核查；标准公共导出尚未通过；运行覆盖为 `partial`。** 本文是收尾与恢复入口，不授权自动启动下一阶段来源、模型、GUI、监测或 GitHub 工作。

## 当前固定候选

- 唯一当前验收 run：`inv-9aa6df1cfc94`。本地入口：`.local/d19-query-loop/live-3/run-summary.json`；原调查库：同目录 `investigation-workspace/investigation.sqlite`；原冻结事实：`derived-export-workspace/frozen-report-data.original.json`。前两次 `inv-598b0dd34d31` 和 `inv-247de301b8f1` 保持原样、各为 `partial`，不得合并账本或回填本 run。
- 两来源查询均由获准参照库真实 RAG 命中 `ev-75676d0716dc956425aca560` 支持：文档 `doc-d7505345776588ba562afc9b`、版本 `ver-de87500973b0c46e43bbe417`、PDF 物理第 1 页。查询、词项依据、请求、候选与截断见派生报告目录中的 `search-history.json`。每来源一条初始查询，各只取一页五候选；未为演示而额外修订。
- 新获取开放论文：OpenAlex `W2100100522`、DOI `10.1039/c4ee01303d`，58 页 PDF，发现库 `doc-a36059a433ed2af5e9ad4a5f` / `ver-854bebf45b46956be8564d0b`。论文为综述，不能当作本轮新实验。
- 新获取专利文本：OPS `WO2026182370A1` 一份 XML，发现库 `doc-919616a2d08e7c6784331bd4` / `ver-9ae4903902f5401f21d8707e`。此公开号与 P4 相同，但本 run 有独立请求、原始版本与入库记录；不声称发现了新的专利族。
- 同一独立发现库为 2 文档、1,589 条证据；论文和专利各 6 条 RAG 命中一次性 attach 到本 run 正式事实。冻结 ReportData 为 78 evidence、10 findings、10 claims。10/10 claim 的引文、document/version/locator 对上原文。论文 PDF 物理页 1/5/10/42 和专利 claim 16、说明书 p278/p282/p328/p336 经独立核对；专利的 70℃、1 M KOH、5.0 cc/min、1 A/cm²、5 小时及 1.11%/0.64%/0.21% 保持原文条件，不推论长期耐碱稳定性。
- 实际额度：OpenAlex 搜索 1/1、OPS HTTP 7/8、论文获取 1/4（2,334,479 字节）、来源总调用 8/9、服务任务 8/10、保存的宿主答案 8/12。没有独立宿主尝试总账可证明未保存的失败答案次数；不要将 8 份已保存答案表述为完整账单。

## 有效验收与未通过门槛

核心同 run 证据闭环通过：两类新正文各有独立发现库版本，共同进入正式事实，中文技术报告和主题综述的已写主张有可定位原文支持。报告区分综述讨论、专利权利要求与 5 小时实测，不作跨来源性能排名。检索各一页五候选、专利化学式图片与表格布局未充分复原、测量方向和长期耐碱仍待人工，因此运行/科学覆盖正确保持 `partial`。

**标准公共导出未通过。** `InvestigationService.export_report()` 在 `bibliography.bib` 遇到冻结书目 `type=paper`，现有 `investigation_reporting._bibtex()` 不接受该枚举。原 `frozen_reports` 和原始事实不改动。`derived-export-workspace/` 中的双报告、canonical JSON、检索历史等 10 件产物是**派生导出**：仅内存副本的一条 `bibliography[3].type` 从 `paper` 映射为 BibTeX 的 `article`；`derived-export-provenance.json`、`frozen-report-data.original.json` 和 `report-data.derived-input.json` 可核对该唯一差异。派生报告可审阅，不能冒充公共 `service.export_report` 验收通过。

当前没有新增来源/模型预算需求。隔离安装版在下载顺序修正后，受影响离线测试 16 项通过；第三 run 不靠该测试声明科学通过。旧 P3/P4、前两 run、本地参照库与密文保留，不推送 GitHub。

## 下一步计划与授权边界

1. **待用户明示批准一个范围外文件后修正公共导出。** 仅改 `src/research_harness/investigation_reporting.py` 的 BibTeX 类型映射，让现有 `paper` 按 `article` 渲染，保持 frozen ReportData 字段原样；在既有相关测试中添加一个最小回归用例。该文件不在本轮用户限定的开发路径内，故当前未修改。
2. 只用 `inv-9aa6df1cfc94` 原冻结库离线重试 `service.export_report()`，核对标准 Markdown/HTML、canonical JSON、BibTeX、CSV、search-history 共用同一 run，重开/重复导出不新增 HTTP、模型任务或预算。对比原冻结事实和报告主张，不改旧快照。若导出器仍失败，停在失败层诊断，不增加网络预算或另开 run。
3. 标准导出通过后可将本阶段写为“**同 run 双全文有界闭环通过；检索与科学覆盖 partial**”。之后另议扩大检索、真正查询修订的真实案例、跨文献科学评价或 GUI；本 handoff 不批准执行它们。
