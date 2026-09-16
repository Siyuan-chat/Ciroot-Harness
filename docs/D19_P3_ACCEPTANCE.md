# D19-P3 阶段验收

2026-09-16。最终结论：新增 PDF 正文解析、独立发现库及报告证据接线通过相应工程检查；C3 科学小样为 partial，未达到跨文献正式引用及标准导出门槛。本轮在冻结范围和预算内结束。

后续用户已批准有限修订，修订后的标准导出与离线跨文献小样已通过，见 [D19_P3_REVISION.md](D19_P3_REVISION.md)。下文保留首轮验收事实，不以新结果覆盖旧失败记录。

## 已验收结果

| 项目 | 结论 | 主要证据 |
|---|---|---|
| 原库起始状态 | 与 P2 一致：23 文档、23 版本、8,820 条证据及同一配置 | `astra/reference-before.json` |
| 独立 parser | Docling 2.126.0 实际安装/导入及产品 prepare 路径成功；pip 安装退出 0 | `install-escalated.log`、`runner.log`、`astra/parser-runtime-freeze.txt` |
| 真实正文解析 | 协议 PDF 26 页、368 个 block；首次 prepare 约 173.148 秒，缓存复用约 0.047 秒 | `c0_c1_result.json`、实际 `discovery_workspace/parse-cache/` |
| 表格提取 | **未通过内容完整性检查**：抽查表格只有标题及空单元格，原 PDF 有数据 | `astra/c1-cache-inspection.json`、`astra/protocol-page-3.png` |
| 独立发现库 | 1 文档、1 版本、395 条 evidence；实际 Qdrant 395 点，重复导入/重启后检索成功 | `c2_result.json`、`astra/c2-independent.json` |
| 身份关联 | 已下载 OpenAlex 文档与 RAG document/version 通过 DOI 及已有内容记录对应 | `astra/c2-identity-map.json` |
| 报告事实接线 | 安装产物的 49 项相关测试通过，实际从独立 target 导入 | `astra/installed-bridge.xml`、`astra/wheel/` |

证据路径均相对 `.local/d19-p3/`，为被忽略的本地运行材料。P2 的 90/90、13/13、此次实现者自测及独立检查分别记录，不相加为总成绩。

## 验收边界

绿氢协议 PDF 仅验证工程路径，不能作为 AEM 科学相关性样本。程序 `coverage=full_text` 表示每页有文本，不保证表格数值完整；该缺口不修改旧缓存或冻结参照库，而随研究结论保留。依赖缺项已经补齐且真实解析成功，但旧 P2 安装中止的唯一原因仍不能从截断日志确定。

报告接线提供 `attach_discovery_evidence`：将已获取文档的 RAG 证据显式绑定到尚未提交的分析任务，baseline、原有页证据及 RAG 证据共享后续引用验证。事实变化递增任务版本，旧领取版本被拒绝；同输入复用不增版本；分析或业务判断提交后不能修改事实。没有新增来源、模型 API、状态机、UI 或监测任务。

本次安装版测试复用旧调查依赖环境，通过独立 target 安装新 wheel；它不是全新机器的完整安装验收。原生科学调用、双正文质量、实际全文引用及恢复行为由 C3 单独给证据。

## 真实科学小样

实际 Luna 调用了原库、生成查询并执行角色任务。首次网络失败运行保留；恢复运行 `inv-fcc548428db7` 下载库外 DOI `10.1039/d0ee01133a` 的 34 页 perspective，解析并导入独立库，产生 585 条证据。5 条 RAG 命中已附加到分析事实，但最终 5 条 claim 全部引用 pypdf 页级证据，未使用原库 baseline 或新 RAG 引用。因此，“能够接入证据”通过，不等于“科学写作实际采用证据”通过。

Astra 对实际 PDF 第 1、2、4、12、25 页核查：阳离子与主链共同影响稳定性、芳醚降解、浸泡/IEC 方法、RH 与电导率的关系有原文支持。第 25 页确有无醚芳香材料脆性的讨论，但分析 finding 将其错误标为原库第 9 页；正文虽改用新论文第 25 页，却挂到电导率 claim，仍不算完整的 finding→claim 对应。第五条 claim 的短引句“protocols have been”不足以单独证明文献类型，其 perspective 身份可由首页独立确认。

新论文第 12 页包含条件依赖和具体测试例子，草稿未充分提取；“没有统一可比条件”不能替代逐项整理已报告条件。旧库条件只出现在正文说明中，没有形成正式对照。独立问题 1、2 获得部分支持，问题 3 的新旧文献比较未完成。两个输出是单篇新文献小样草稿，不能称完成主题综述。

标准 `service.export_report` 返回 `ValidationError: bibliography has invalid BibTeX type or key`。Luna 随后在内存副本补 citation_key，调用底层导出生成 Markdown/HTML 等阅读产物；这是旁路草稿，**标准导出未通过**。冻结结果及 ReportData 在 resume 前后保持相等，但该检查不能证明旁路导出的 canonical 内容与冻结 ReportData 完全相同。原失败输出保留，未据此修改产品或数据库。

冻结的模型 verification 把 pypdf 证据误称 Docling，Astra 不采纳该自评。错误记录保留，执行摘要另行更正。

| 合并用量 | 实际 / 上限 |
|---|---|
| 来源 HTTP | 5 / 8 |
| 模型任务 | 8 / 10 |
| 文档下载尝试 | 1 / 1 |
| 下载 HTTP | 11 / 12 |
| 下载字节 | 7,818,339 / 10,485,760 |

用量来自两次 run 的服务账本，见 `science/recovery/aggregate-budget.json`。结束时原库仍为 23 文档、23 版本、8,820 条证据，配置与起始相同，见 `astra/reference-after.json`；未重算哈希。

## 阅读入口与后续范围

- 执行与根因：[D19_P3_EXECUTION.md](D19_P3_EXECUTION.md)。
- 两类草稿位于 `.local/d19-p3/science/recovery/investigation-workspace/reports/inv-fcc548428db7/run-inv-fcc548428db7/`，文件为 `technical_report.zh-CN.md`、`literature_review.zh-CN.md`。
- 原始角色结果、标准导出错误与恢复比较位于 `science/recovery/`；独立 PDF 对照为 `astra/c3-source-pages.json`。

后续建议只处理两个问题：修复 BibTeX key 的标准导出；使用已有全文与证据重做分析至验证，明确绑定旧库及新 RAG，逐项整理测试条件。当前完成任务不可覆写，重做需要另行对齐离线重放/修订方式及任务额度；本轮不新增修订接口、不重开检索、不扩大预算。表格解析和候选优先顺序作为单列后续项，不自动修改。
