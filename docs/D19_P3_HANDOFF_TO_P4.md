# D19-P3 交接：论文闭环已验收，下一步准备专利

日期：2026-09-16。工作区：`C:/Users/Siyuan_ye/Documents/ChatGPT/AEM`。本文件是新对话恢复入口。当前对话到此收口，不保留后台调查或自动跟进任务。

## 1. 先读结论与权威输入

**本次有界论文案例通过独立验收，可以规划专利接入。P4 尚未启动，也没有专利联网或实现预算授权。** 用户最后要求是生成包含下一步计划与本次工作纪律的 handoff。

依次阅读：

1. 本文件，尤其工作纪律和授权边界。
2. [D19_P3_LOOP2_ACCEPTANCE.md](D19_P3_LOOP2_ACCEPTANCE.md)：最终有效验收，不要把早期失败记录当作当前状态。
3. [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) 第 10 节、[INVESTIGATION_EXPERIMENT_PLAN.md](INVESTIGATION_EXPERIMENT_PLAN.md)：P4/P5 原有完整范围。
4. 开始产品修改前遵守仓库 AGENTS.md，读取 PRD、ARCHITECTURE、CONTRACTS、ACCEPTANCE；需要诊断历史才读 [D19_P3_LOOP2.md](D19_P3_LOOP2.md)、[D19_P3_LOOP.md](D19_P3_LOOP.md)。不必从头重放全部对话和日志。

本文件中的相对路径均相对上述工作区；转到另一台机器时，`.local` 运行材料与安装环境不一定随 Git 存在。

## 2. 已完成到什么程度

最终运行：`inv-b7b6c9cbba4e`。正常服务完成规划、真实 OpenAlex 检索、筛选、单篇全文获取、独立 Docling/RAG、分析、综合、双中文正文、核查和标准导出。服务为 `stage=completed / status=partial`，没有 pending。partial 表示候选及全文覆盖有限，不否定本次有界科学验收。

- 原库只读：23 文档、23 版本、8,820 条证据；最终数量与配置和起始一致。没有宣称逐字全库校验。
- 新全文：Mustain 等，2020，DOI `10.1039/d0ee01133a`，34 页，独立发现库 585 条证据，8 条检索证据通过公共 attach 接入。
- 实际分析 payload：48 条事实，含 6 条本地 baseline，全部可正式引用。
- 11 条 finding、12 条 claim、9 个正文分节；正式科学主张使用 3 篇本地综述与 1 篇新 perspective。两个仅有书目内容的片段不作为结论来源。
- 8 个标准导出文件齐全；重开读回和再次导出后结果、ReportData、canonical 字节一致，预算不变。
- 原 PDF 页图核对了三组独立条件：≤4 M NaOH/80°C、8 M NaOH/120°C、5% RH/100°C。不把提取失真的字符、不同试验条件或 AWE 隔膜建议混为 AEMFC 实测结果。

这仍是**已知文献上的有界闭环**，不是陌生文献泛化、完整领域检索、统一材料性能排名或原始实验复现。GUI、干净环境安装、三语完整联合调查、企业监测均不能据此宣称完成。

### 可直接阅读的产物

最终目录：

`C:/Users/Siyuan_ye/Documents/ChatGPT/AEM/.local/d19-p3-loop2-replacement/investigation-workspace/reports/inv-b7b6c9cbba4e/run-inv-b7b6c9cbba4e/`

- [技术调查报告](../.local/d19-p3-loop2-replacement/investigation-workspace/reports/inv-b7b6c9cbba4e/run-inv-b7b6c9cbba4e/technical_report.zh-CN.md)
- [主题综述](../.local/d19-p3-loop2-replacement/investigation-workspace/reports/inv-b7b6c9cbba4e/run-inv-b7b6c9cbba4e/literature_review.zh-CN.md)
- 同目录：canonical JSON、两份 HTML、comparison.csv、human-review.csv、bibliography.bib。阅读条件表优先用 Markdown；现有 HTML 没有把 Markdown 表格转换为原生 table。
- 独立验收证据：`.local/d19-p3-loop2-replacement/astra/final-acceptance.json`、`scientific-body-review.json`、`attach-check.json`、`source-page12-check.json`。
- 导出与用量：同工作目录的 `final-export-selftest.json`、`host-generation-ledger.json`。

### 已冻结用量，不可给下一阶段当作剩余额度

失败运行与替代运行累计：来源请求 5/8，下载尝试 1/1，下载 HTTP 11/12，7,818,339/10,485,760 字节，服务角色 8/8，执行者台账记录宿主生成及修订 12/12。替代运行是用户明确批准的例外；不自动重开下一轮。

## 3. 今天的工作纪律——新对话继续遵守

用户明确认可本次对话的纪律性并要求写入交接。这是继续工作的约定，不是“今天没有发生错误”的声明；执行中确有路径、权限和导出问题，均保留失败证据后定位修复。

1. **分工固定。** Astra 给出范围、指令、根因与独立验收；Luna 写脚本、后台运行、真实生成角色结果、自测并交固定候选；Terra 只按 Astra 的明确任务做核心代码修复。没有必要不要增加代理。同一产物只有一个写入者。新对话不假定旧代理可直接复用；按用户指定模型创建必要角色，并使用真实支持的模型设置。
2. **先明确本阶段交付物、验收和排除项。** 已授权范围内自主处理常规可逆选择，减少用户干预；禁止未对齐修改。新增来源、预算、运行次数、产品接口或其它范围，先停下相关部分，说明变化再确认。先完成可做的诊断与准备，交给用户批准具体方案，不只问抽象问题。
3. **以完成事件推进，不做空轮询。** 后台进程隐藏运行；优先完成通知或 30–60 秒有界事件等待。只有新产物、状态变化或明确失败才推进下一阶段；不连续读同一日志、不频繁查进程、不重复发指令。进度沟通说实际变化，避免空泛重复。
4. **两次修正无进展就先诊断。** Astra 重新核对观察对象、执行身份和失败层，再交 Terra/Luna 修复；不要堆补丁、反复重试或降低验收门槛。
5. **执行者自检，Astra 集中反馈。** 一次交代权威输入、文件归属、产物和检查。按固定候选合并反馈，避免零散往返。提交不可覆写角色前设两个门：分析 payload 确认新旧证据均可引用；综合/写作确认主张、条件、引用和排版。不要等导出后才首次读正文。
6. **验证实际执行环境。** 普通沙箱预检不代表联网进程可用。联网步骤通过正规工具权限机制执行；在真正执行进程内核对并记录模块路径，不靠脚本文本或另一个进程的检查推断。涉及批准时解释具体来源和原因，不索要已经给过的授权。
7. **预算真实累计。** 失败请求、重试、下载尝试和角色答案修订都计账。区分服务任务数、实际宿主生成次数与尚未执行的预计次数。不得换 run 清零、修改已完成任务或数据库凑通过。纯脚本搬运与无新科学内容的机械元数据同步单独注明，不伪装成模型生成。
8. **不反复查 hash，不做过度防御性编程。** 复用有效检查，只重跑受改动影响的部分。现有来源映射所需内容身份可以保留；不要为交接、轮询或每一步重复计算。优先最小成熟接口，不新增第二套状态机、无关抽象或全面加固工程。
9. **证据边界不让步。** 保留原文、条件、版本和失败产物；quote 是原证据连续子串还不够，必须支持整条主张。题录不是研究结果，综述不是原始实验，建议不是实测；缺失就保留缺失。数值/符号提取可疑时看原始页面，不猜。
10. **最后验证用户拿到的文件。** 命令成功、单元测试通过、模型说 supported，均不能替代真实输出验收。读回最终正文与导出，重开检查只读状态/结果并复导出，不随意调用会推进流程的 resume。
11. **文档供用户读懂。** 默认中文，先说结果、原因和下一步；工程路径与沿革集中放附件/交接。一次通过、反馈后通过、partial、未验证分别写清。达到本阶段条件即停止，不自动追加 GUI、监测、发布或新实验。

## 4. 恢复时必须知道的工程事实

### 安装与运行路径

| 用途 | 当前有效位置 |
|---|---|
| 最终已验证安装物 | `.local/d19-p3-loop/engineering/target-host-review` |
| 对应 wheel | `.local/d19-p3-loop/engineering/wheelhouse-review/research_harness-0.1.0-py3-none-any.whl` |
| 调查服务 Python | `.local/d19-p2/venv/Scripts/python.exe` |
| Docling Python | `.local/d19-p3/parser/Scripts/python.exe` |
| RAG 检索 Python | `.local/d19-p2/rag-restored/venv/Scripts/python.exe` |
| 原库 SQLite | `.local/rag-acceptance/real-v3/workspace/rag.sqlite` |
| 最终调查工作区 | `.local/d19-p3-loop2-replacement/investigation-workspace` |
| 最终发现库 | `.local/d19-p3-loop2-replacement/discovery-workspace` |

Python venv 自带的 `research_harness` 可能是旧版。不能只写 `import research_harness` 就认定是最终版本。旧 `target-fixed` 包子目录存在受限 ACL，普通沙箱与沙箱外主体可读性不同；`target-host-review` 是实际沙箱外身份安装并验证的目标。也不要反向假定普通沙箱能读它。选择实际执行身份后做一次准确模块核对；若需要新安装，从已有 wheel 离线 `--no-deps --no-index` 安装到隔离目录，不扩大系统 ACL。

本轮主要产品变化：调查事实合并与公共发现库 attach、候选优先顺序保持、包内角色说明、BibTeX 安全默认键、仅投影排除 `visibility`、仅投影将 `review` 映射 `article`。canonical 保留原元数据，未知字段/类型仍拒绝。当前源码与测试留有未提交修改；`git status` 已确认，**未 commit/push**。不要 reset、清理或覆盖这些工作；同步 GitHub 需另有授权。

有效测试：早期修复安装版 37 项相关检查通过；最后仅导出投影变化，源码与最终安装版各 13 项 reporting 检查通过；最终真实运行标准导出与重开通过。不要把不同批次测试简单累加为成绩，也不因换对话重复整套检查。

旧失败运行 `inv-90e7bbe335c9`、`inv-5f669903cdbe` 保留。当前 `resume_investigation` 不是 source 失败后的重新开启接口，不应当作通用重试调用；未实现新 revision/reopen API。历史网络记录只有归一化错误时，不要补写确切 WinError 或远端原因。

## 5. 下一步计划：P4 的专利小阶段（提案，待启动授权）

目标：沿用“阳离子基团/聚合物骨架—耐碱稳定性—OH−电导率”的问题，先跑通**单次专利调查**，再考虑完整论文—专利联合调查。建议一个来源、一个专利族、少量公开文本、中文报告。这个小阶段不等于 P4 全部三语 E01–E07/O01–O04 验收。

现状已核实：`src/research_harness/providers.py` 有 EPO OPS 认证/检索适配草稿，主要解析公开编号等候选字段；正常 `InvestigationService` 的 live 来源目前只接受 OpenAlex。存在 `patent_search` 角色和合成框架，**不代表真实专利来源、全文或族关系已接通**。EPO 凭据当前是否可用尚未重新核实，不能沿用旧“缺失”记录作为现状。

| 步骤 | 计划内容 | 放行条件 |
|---|---|---|
| P4a 来源与执行预检 | 核查 EPO 凭据存在状态（不输出值）、实际执行环境和当前官方接口；先列出最小代码接线及请求预算 | 凭据/访问前提明确；用户认可具体实施范围、来源调用及角色预算 |
| P4b 小流量接通 | 按明确合同接入正常服务，验证检索、分页、公开版本和可获取正文；优先原生 XML，按真实可用性处理 PDF | 真实来源请求有记录；失败、缺正文、配额和预算可追踪；不靠手填 fixture 冒充 live |
| P4c 单族证据闭环 | 选择一个相关专利族，保留每份公开文本的独立身份；区分权利要求、说明书、实施例；进入独立发现库和正式 facts | 公开号、kind、公开版本不混用；claim/段落/XML定位或物理页可回查；缺失不补造 |
| P4d 论文—专利对照 | 用当前已验收论文证据对照专利技术路线、所述范围和实施例支持，形成中文报告与待核实清单 | 专利宣称与实验支持分开；正式引用覆盖双方；标准导出、重开及独立验收通过 |

预算数值现在不代定：先核查接口调用构成、认证/正文可用性，再提出一次完整小样的明确上限；认证、失败和重试是否计入须事先写清。不继承已经结束的 P3 请求余量。新来源实现由 Terra 单写，Luna 负责脚本/后台运行/自测与角色结果，Astra 负责计划及验收。

首轮排除：真实公司保密资料、公司业务該非判定、持续监测/定时任务、全地区/三语完整覆盖、GUI、GitHub 发布、侵权/FTO或法律有效性结论。技术相关性可以按当前研究问题判断；企业业务相关性需要后续明确公司范围。不得把“检索不到”当“不相关”，不得把族成员视为内容完全相同。

## 6. 给新对话的直接起步指令

> 阅读本 handoff 和最终验收记录，保留当前源码、原库与所有冻结运行。沿用第 3 节纪律。先做专利 P4a 的只读准备：核实当前 EPO 接线/凭据存在状态与实际执行环境，给出一个专利族小样的具体实施范围、请求及角色预算、验收条件。尚未获得启动授权时不改产品、不发专利网络请求、不创建调查或监测。用户批准具体计划后按 Astra→Luna/Terra 分工推进，不重复索要已给过的授权。不要重跑已完成的 P3。

本 handoff 已足够恢复目标与约束；仅在出现具体缺口时读取下层证据。不需要用户重新解释今天的执行纪律。
