# D18 — 本地文献 RAG 与 Codex 接入

2026-09-10。用户已批准开始。当前阶段取代 D2 的“停止开发”边界；D2 已通过的行为保留。设计者负责计划、诊断和独立验收；Terra/Luna 负责下述明确编码和简单自测。本文是本阶段公共契约与任务书，优先于旧 D1 全量路线和旧 Terra 单人分工。

## 完成目标与范围

用户在 Windows 本地 Codex 中选择 Luna，能通过本地工具检索真实 AEM 文献、补读上下文，并得到可以核对原文的回答。完成的是本地 RAG 与宿主调用，不是完整科学调查系统。23 篇英文 PDF、584 页来自 literature/aem_oa_reviews/catalog.json；只读取 catalog.records 中的 file，不扫描 rejected、日志或检索响应。源目录只读；数据、原文副本、模型缓存、索引和验收产物保持 Git 忽略。

本地解析、本地 Embedding、本地关键词/向量混合检索。相关证据通过工具结果进入 Codex 模型上下文，沿用用户已允许的片段发送。订阅认证由 Codex 管理，RAG 不读取或复制 Codex 凭据、不调用生成模型。自带模型 API 模式只固定下述通用证据接口与模型适配契约，本轮不实现生成模型调用器。文献检索 API 编排、GUI、HTTP 服务、自动目录监控和发布不在本轮。

## 负责人及工作区

- 设计任务：本文、PRD/架构/验收/决策的一致性；独立原文与检索检查；提交快照验收和直接修正反馈。不得修改产品代码。
- Terra：RAG 解析、存储、向量及关键词检索、Python/CLI 服务；依赖/打包、公共应用边界和最终集成。工作树 .local/rag-worktrees/terra，分支 codex/rag-core。
- Luna：MCP STDIO 包装、宿主配置示例、三语接入说明及协议简单测试。工作树 .local/rag-worktrees/luna，分支 codex/rag-mcp。只编辑 rag_mcp.py、tests/test_rag_mcp.py、docs/RAG_USAGE.* 和 examples/rag-mcp*.json；依赖及其它改动需求发给 Terra。
- 两人不得改设计规范或彼此所属代码。实现检查点必须提交并报告 hash、可复制命令、实际输出和剩余问题。产品集成由 Terra 完成，设计者只整合已验收提交。

## 公共服务契约（冻结 v1）

实现 research_harness.rag.RagLibrary(workspace, *, embedding_model=None)。数据和索引属于该 workspace；close() 与上下文管理器释放资源。复用既有能力但不改变 D2 fixture 语义；必要时新增 RAG 专用表/模块，不复制调查状态机。服务不打印，返回普通 JSON 兼容 dict/list。异常使用 RagError(code, message)，to_dict() 返回安全 code/message，不泄漏输入值或底层异常内容。

1. import_library(catalog_path, *, limit=None)：读取 records/file 及元数据；文件路径相对 catalog 目录，拒绝越出选定目录；只处理 PDF/TXT。返回 {outcome, imported, reused, failed, documents, errors}。documents 是处理过的文档摘要，errors 含文档 ID（如已知）和安全 code/message。outcome 为 completed/partial/failed。逐文件失败继续，原始文件不改写。DOI（无 DOI 时来源/文件身份）决定文档 ID；内容改变生成新 version_id；相同内容不重算。解析完成且入索引成功才计 imported/reused。导入不因缺生成模型 key 失败。
2. search_evidence(query, *, top_k=8, filters=None)：返回 {query, items, snapshot_version_ids, diagnostics}。filters 仅支持 document_ids、version_ids、doi、year_min、year_max、types；未知字段返回 RH_RAG_INVALID_INPUT；条件以 AND 合并。默认只检索每文档最新成功版本；指定 version_ids 可读取已保留版本。先过滤再排序，严禁混入范围外证据。top_k 1–30，query 非空。diagnostics 至少包含 mode=hybrid、embedding_model、lexical/vector 命中计数和已知 coverage 限制。不静默退回纯关键词并宣称 RAG 成功。
3. get_evidence_context(evidence_id, *, before=1, after=1)：返回 {evidence_id, items}；前后各 0–3 个同文档同版本片段，包含命中片段，保持原文顺序。未知 ID 返回 RH_RAG_NOT_FOUND。表格上下文保留标题、表头、单位和脚注，必要时作为一个较大块，显式说明解析缺口。
4. get_document(document_id)：返回文档元数据、当前 version_id、已保存 versions、页数、解析器、coverage/errors 和可打开的 source_path；原文题名不被翻译替换。
5. get_library_status()：返回 {document_count, version_count, evidence_count, indexed_document_count, failed_document_count, embedding_model, index_status, documents}。documents 含 document_id/title/doi/type/year/current_version_id/parse_status，支持模型发现和筛选资料。索引状态必须来自实际数据。

每条 evidence item 必须含 evidence_id、document_id、version_id、text、title、doi（可 null）、year（可 null）、document_type、source_path、locator、section（可 null）、role、quality。locator 对 PDF 含 page（物理页码，从 1 开始）、bbox（可 null，记录坐标体系）、printed_page（可 null）；多页片段用 pages/provenance 记录，不编印刷页码。TXT 用行范围。检索项可附 score，解释为检索排序值，不能当科学置信度。稳定 ID 不随语言、排序或查询变化。quality 明确 OCR/表格/阅读顺序限制。

MCP 暴露同名五项工具（close 不暴露），query 等参数同上。workspace、允许的 catalog 在服务启动时配置，工具不接受任意 workspace 或任意 import 路径；import_library 工具只接收 limit。读工具标注 readOnlyHint，导入标注写入。使用成熟 MCP Python SDK 的公开接口，STDIO stdout 仅供协议，诊断到 stderr。不引入 HTTP 和第二套调度框架。CLI/工具调用都复用 RagLibrary；对 SDK 异常进行安全错误映射。MCP 的输出字段不嵌入框架对象。

API 用户预留边界：其模型调用器接收 question + evidence items + 可信任务说明，输出 answer + citations[{evidence_id, quote}] + gaps。模型名不写死；后续同协议服务配置 endpoint/model/key_env，不同协议添加适配器。quote 必须来自原证据，引用核查继续由应用边界承担。本轮只写契约，不实现空工厂或占位 provider。

## 技术约束与实现次序

沿用 Docling provenance、FastEmbed 多语模型、Qdrant、LlamaIndex 必要检索模块的架构方向。先验证可用公开接口和本机资源，模型 ID/许可证/维度/版本及依赖锁定由 Terra 实测记录。Embedding 或切块配置改变必须明确拒绝旧索引或在新集合重建；不得混用向量。中日文问题检索英文论文必须真实执行，不能用预设翻译字典代替向量化。

单写入者即可，避免多个进程同时打开 embedded Qdrant；遇忙给明确错误。保留可重建索引与原始证据，重复导入不重复建档。先试三个代表文件：2022 Khalid 原始研究、2023 Clemens 交联综述、2024 Henkensmeier 长综述。正常 PDF 优先解析文本；OCR/复杂结构式未验证时明确质量限制。若库/模型在当前环境不能工作，提供具体错误及最小替代建议，由设计者裁定，不能静默换成 fixture。

2026-09-10 性能调整：三篇 102 页初次建库耗时约 49 分钟，后续多语诊断未通过。因此增加模型无关的本地解析缓存，键包含源内容哈希、解析器指纹及 Docling 版本。`prepare_library(catalog_path, limit=None)` / CLI `prepare` 只生成解析缓存，返回 prepared/reused/failed、逐文档状态和安全错误；不得计为 indexed/imported，不接入 MCP 工具、不增加状态机。正常 import 复用有效缓存，模型检索改进与剩余文献解析可并行。损坏缓存应重新解析并可诊断，写入须原子完成。解析器配置变化不能复用旧缓存。该步骤只是加速与分离处理阶段，未降低原文或检索验收标准。

检查点 C1：Terra 真实小样本解析/检索，Luna 独立协议包装及显式 fake 测试。C2：集成真实服务，全部 23 篇完成导入或逐项说明未成功文档；Windows 安装包可运行。C3：实际 Codex Luna 使用 + 独立验收。每阶段先简单自测、提交再继续明确工作，不等用户人工转交。

## 独立验收与停止标准

| ID | 可观察通过条件 |
|---|---|
| RG01 | 安装包导入上述清单；23 篇文件都有明确状态，成功文献实际可检索。失败不可计为成功；未解决失败阻断“全库完成”。 |
| RG02 | 抽查三篇不同版式的正文和一张性能表，text/page/表头/单位/条件可回溯原文。无法可靠解析的表不输出确定数值关系。 |
| RG03 | 设计者冻结小型相关证据集合后执行中/英/日查询；每种语言都有有效命中。检索 Recall@8 按明确分母记录，接受门槛在首次评分前冻结。精确 DOI、文档/版本过滤不得误混。 |
| RG04 | 重复导入不增文档/证据；受控文本更新产生新版本；旧 evidence_id 和 context 仍可访问；模型配置不匹配不能混索引。 |
| RG05 | MCP 实际 initialize/list_tools/call_tool，服务成功与安全失败均结构化；安装后由 Codex 中的 Luna 检索、补读、引用真实文献。协议客户端测试不代替最后宿主验收。 |
| RG06 | 原文/索引本地，检索不依赖生成模型 key；模型权重首次下载单独记录。科学回答区分综述转述、实验研究、未知/不可比条件。 |
| RG07 | 三语最短指南、真实依赖/模型与调用证据齐备；受影响 D2 行为不回归；资料/数据库/凭据不进提交。 |

达到 RG01–RG07 后交付并停止，不追加检索来源编排、GUI、生成模型 API 实现或发布。无法从当前工具会话热加载新 MCP 时，记录安装和真实协议验证，给出最短重启/新会话步骤，宿主验收保持 pending，不能以子进程协议成功宣称 Codex 已接通。

### D18 索引迁移与查询规划边界

默认检索模型调整为官方 `intfloat/multilingual-e5-small`，文档使用 `passage: `、查询使用 `query: ` 前缀；尚未迁移的 MiniLM 库可在显式选择原模型时读取。新增 Python `rebuild_index()` / CLI `rebuild`：只使用已保存证据重新嵌入，不重解析 PDF、不更改 evidence/document/version ID 或来源。新向量写入独立集合，数量核验后以 SQLite 事务切换活动集合与配置；失败保留原活动索引。本轮不向 MCP 增加重建工具。模型不匹配的普通 import/search 仍须拒绝混用。

RG03 的宿主路径明确为原问→宿主模型查询规划→本地混合检索；英文语料采用英文检索式，点名论文时可使用已知元数据过滤。模型负责规划，不由本地服务调用生成 API。原文查询直接检索的限制须单独报告。中、英、日三组分别规划，不将平行英文问题提供给中日规划实例；原问和实际检索式均归档，不能在查看命中结果后反复选取最高分查询而不披露。

2026-09-10 排序修正：词法分支采用BM25Okapi默认参数和固定RRF k=60融合向量排名，使用相同的query/corpus token规范化。仅ASCII纯字母做标准Snowball英文词干；保留数字、连字符及CJK token。不改原文、切块、向量或evidence ID；当前候选快照词法缓存有界且版本变更失效。词法全零时只采用有效向量排名，不把任意零分候选当作词法命中。依赖缺失仍返回安全错误。质量阈值及首次失败记录保持可追溯。
