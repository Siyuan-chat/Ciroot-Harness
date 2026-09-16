# D19-P3 有限修订

2026-09-16。用户在 P3 验收后明确同意启动下一步。本轮已完成：标准 BibTeX 导出修复通过安装版验收；使用现有材料的跨文献引用及中文双报告小样通过本轮独立检查。报告仍保留 partial，表示来源覆盖、原始研究追溯及定量可比性尚不完整，不表示本轮导出修复失败。

## 范围与分工

- Terra：定位并最小修复标准导出键生成，保留合法键和严格校验，完成相关自测。
- Luna：在 `.local/d19-p3-revision/` 编写后台脚本，使用已有真实材料完成离线科学角色和自检；脚本不代写科学答案。
- Astra：选择最小离线重放方式，审阅固定候选、安装版标准导出及全部关键主张，合并反馈。

网络请求与下载为 0。新增角色任务上限 12 个，包含首轮和必要修订；不与上一轮的 8 个任务混算。继续保持原库、旧运行和旧报告不变，不反复计算 hash。未完成任务的重放不通过修改旧数据库状态实现。

表格解析、候选优先序、GUI、监测、API 扩展及 GitHub 同步均不在本轮范围。无新证据不轮询；相同问题两轮无进展，由 Astra 先定位根因。

## 验收条件

1. 安装版 `InvestigationService.export_report` 对上一轮真实事实的独立副本成功，不补写 citation_key 绕过标准路径；冻结 ReportData 不变，保留旧旁路产物。
2. 修订稿的 findings 和 claims 实际引用原库及新增 Docling 证据，身份、原文及物理页能回查。不同文献分别建立 claim，正文对照引用双方，不强行把多个文档塞入仅允许单文档的 claim。
3. 提取已报告的浓度、温度、时间、测试方式和指标，缺失项保留缺失；综述转述与原始实验分开，不将条件不同的数据排序。
4. 两类中文正文基于同一新事实文件，技术报告回答问题，主题综述跨文献综合；全部关键科学主张由 Astra 核对。
5. 离线重放与新 live 调查明确区分。使用既有公开渲染接口时，不将其称为新的服务编排验收；标准服务导出另行验证。

## 当前状态

离线方式已确定：保留旧库及 Docling 实际证据 ID，在新目录生成五类角色 JSON，使用公共 schema、ReportData 构建与 `export_reports` 进行工件级修订。当前服务的 live 模式必须经过采集，synthetic 模式会重新归一化证据，均不用于冒充本次离线重跑；不新增修订 API。标准 `service.export_report` 使用旧运行 SQLite 的独立备份验证，原数据库和报告不动。

Terra 已定位缺省 DOI 含 `/` 导致引用键校验失败：仅对不合法的缺省 DOI/ID 生成稳定键，保留合法旧键和显式校验。安装版验证由 Luna 后台脚本执行；科学修订并行进行。最终记录实际任务数、产物路径、测试与科学结论。

## 审阅记录

Astra 已核对新论文第 12 页及原库两篇综述的实际 PDF 页面。QPPO3 的 300 h 浸泡与 100 h OCV 分列；前者的这段文字描述测试条件，没有单独给出稳定性结果，不能把后句器件评价移植到浸泡。SEBS 的恒电压运行与电压损失描述按原文保留，不推断两种控制条件同时成立。两条不同 KOH 器件案例须分别绑定所在证据块。

安装版标准导出已通过，冻结 ReportData 与 canonical 一致、任务和预算不变。复导出已采用“首次导出保存字节快照，再与第二次比较”，结果一致。正式 artifact 为 8 项（canonical、两类 MD/HTML、两个 CSV、BibTeX），另有 manifest；早期任务书误写 9 项已更正，不增加虚构产物。

## 工程验收：通过

- 安装目标：`.local/d19-p3-revision/engineering/revision-target/`，实际模块路径确认指向该目录。
- 标准服务在 `engineering/service-copy/` 独立副本上导出，未补写 citation_key 或旁路修复事实；8 项产物完整。
- 重开 resume 后重复导出逐项字节相等，冻结数据与导出 canonical 相等；旧 run 模型任务 7→7，预算不变。
- 定向检查：reporting、report_data、rag_bridge 共 21 项测试通过。
- 证据：`engineering/REVISION_EXPORT_RESULT.md`、`revision_export_result.json`、`targeted-tests.log`。

本轮复用已有依赖、构建 wheel 安装到独立 target，不声称新机器安装验收。旧内容的科学缺口仍属于 P3 历史记录；这里通过的是标准导出修复。

## 科学小样验收：本轮修订通过

最终输入有原库 6 条和新发现库 7 条证据。Astra 逐条比对实际 SQLite，13 条的文档/版本、正文、原 locator 字段全部一致；原库仍为 23 文档、23 版本、8,820 条证据，同一配置。

13 条正式 claim 实际引用 11 条证据，来自 4 篇文献（原库 3 篇及新增 perspective 1 篇），两条备用输入不计作已引用证据。Astra 逐条检查 finding→claim→原文/定位关系，并读回实际导出的两份正文。正文及条件表已恢复具体引用，书目保留已引用的四篇；不是仅将新旧证据放在输入而未用于报告。

本轮处理了上一轮的错位引用和测试混用：QPPO3 浸泡与 OCV 分列，两个 KOH 器件案例独立引用，SEBS 按原文区分运行条件与损失描述。技术报告包含条件表，主题综述按设计共识、条件依赖、电导率和缺口组织。已有资料支持机制层面的跨文献综合，但不同测试不能用于材料寿命或电导率排名。

导出使用安装 target 的公共 `export_reports`，没有给 facts 补 citation_key；最终 canonical 与输入 ReportData 完全相等，8 项 artifact 加 manifest 均已生成。该路径为明确标记的离线工件修订，不是新的 InvestigationService run，不声称 live 科学编排自动重试已经通过。

| 记录 | 结果 |
|---|---|
| 新增角色任务 | 9 / 12：首次五角色；分析修订 1，写作修订 2，核查修订 1 |
| 新增检索/网络请求/下载 | 0 |
| 标准导出相关测试 | 21 项通过 |
| 正式科学 claim | 13 条，全部原文与身份绑定有效；语义按上述范围核查 |
| 原库 | 数量与配置不变 |
| 报告状态 | partial，保留来源与二手证据边界 |

## 阅读与恢复入口

最终目录：`.local/d19-p3-revision/exported/reports/offline-replay-c3-20260916-export/v2/`。

- [技术调查报告](../.local/d19-p3-revision/exported/reports/offline-replay-c3-20260916-export/v2/technical_report.zh-CN.md)：条件表、结构机制与电导率关系。
- [主题综述](../.local/d19-p3-revision/exported/reports/offline-replay-c3-20260916-export/v2/literature_review.zh-CN.md)：跨文献主题综合。
- 同目录包含 HTML、comparison.csv、human-review.csv、bibliography.bib 及 canonical；中文 Markdown 为首选阅读入口。
- 实际证据与角色文件：`.local/d19-p3-revision/evidence-prep.json`、`role-*.json`、`report-data.offline.v2.json`、`role-counts.json`。
- 独立验收：`astra/evidence-independent.json`、`astra/source-checks.json`、`astra/final-artifact-check.json`；导出自测为 `export-selftest-v2.json`，元数据终检为 `astra/final-v2-check.json`。
- 标准入口复现：`engineering/rerun_export_checks.py`；最终工件导出：`export_v2_reports.py`。两者均使用已有本地材料。

本轮到此结束。旧 P3 记录与旁路草稿保留；表格提取、筛选优先序、完整 live 重跑、原始研究追溯和定量比较仍是另行对齐的后续项。本次未提交或推送 GitHub，未启用持续轮询或后台监测。
