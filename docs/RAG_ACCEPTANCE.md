# D18 独立验收记录

2026-09-10。状态：实现与独立验收进行中；未宣称 RAG 通过。

## 输入与评价冻结

真实输入为 `literature/aem_oa_reviews/catalog.json` 中的 23 篇英文全文。复用 D17 下载完整性证据，本轮不重新下载或重复全量哈希核查。

独立参考采用三篇不同版式论文：Khalid et al. 2022（10.3390/membranes12100989）、Clemens et al. 2023（10.3390/polym15061534）、Henkensmeier et al. 2024（10.1021/acs.chemrev.3c00694）。设计者先阅读原文并渲染核对物理页码，再冻结 6 组相关证据及每组中文/英文/日文查询，共 18 问。查询与对应证据保存在忽略目录 `.local/rag-acceptance/evaluation-v1.json`，实现者未据此调参。

首次检索调用前的原文审计发现，单个子串 `IEC` 会误命中 `pieces`，`hydrophobic` 也不足以保证命中亲/疏水交联链比较段落。因此冻结 v2 仅收紧证据判定：E02 要求 hydrophilic/hydrophobic/conductivities 同现，E05 要求 table 及 IEC/PI-15/PI-20 同现，E06 要求 table/PiperION。18 个问题、页码、top_k、通过门槛不变。v1 保留，SHA256 为 dc1058990da104ad645ce0c8320fec09d869a4672ec7fb125db61a6a1b905fdb；v2 SHA256 为 5503a6c55feff2639455699ea3c6e200f588fa5441e862ad8a4baf3e5fd5efe2。本调整发生在任何检索评分之前。

首次评分前固定：top_k=8，18 问中至少 15 问命中指定证据组，每种语言至少 4/6 命中；证据必须包含实际支持文本及正确 DOI/物理页码。记录分子分母和未命中问题。该数字是此小样本中已知证据组的命中率，不是对整库所有相关片段的召回率，也不是全球文献召回率。检索评分与答案科学准确性分开。

原文定位、表格单位/脚注、未知值不补造、文档/版本过滤和原文不覆盖属于不变量，发现错误即须修正，不能用平均检索得分抵消。首轮失败反馈后的复验应明确标为同集回归；如参数依据失败问题调整，则补充新的未见查询，不能将回归成绩表述为独立泛化效果。

## 当前证据

- 已渲染并检查 Khalid 物理页 5、9、10，Clemens 页 7，Henkensmeier 页 31。后一文件含机构封面，物理页码与印刷页码不同，需分开记录。
- 简单 pypdf 文本抽取可包含 MDPI PDF 中不可见的旧排版和邻页文字。其输出只用于独立定位线索，不作为真实 RAG 引用金标准；金标准依据可见页面。
- 本机 Codex CLI 为 0.153.4；用户宿主 `codex login status` 显示 ChatGPT 登录，沙箱身份显示未登录。最终订阅路径以用户宿主、只读 Codex/Luna + 实际 MCP 工具调用验证，不复制凭据。
- Python/协议探针与 Codex 宿主验收分别记录。MCP initialize/list/call 成功尚不能说明模型已正确使用工具并回答。

## 检查点结果

C1、C2、C3 与 RG01–RG07：pending。结果待对应不可变提交和实际产物产生后补充。

## C1 环境诊断与明确实现调整

Docling 2.126.0 默认 ThreadedDoclingParseDocumentBackend 初始化耗时较长，堆栈停留于 docling_parse.pdf_parser 的 C++ renderer 构造，之后进入默认 RapidOCR。该观察不证明死锁。设计者授权保留 Docling 布局/表格/provenance，采用其公开 PyPdfiumDocumentBackend 和 PdfPipelineOptions(do_ocr=False, do_table_structure=True)，先验证一篇可搜索英文 PDF；converter 在库实例内复用。无文本页需标记待 OCR，不承诺扫描件支持。后端/配置变化记录进解析与索引版本。官方接口依据：https://docling-project.github.io/docling/v2/ 、https://docling-project.github.io/docling/_generated/examples/run_with_formats/ 。

## MCP 检查点 76727da

设计者独立复验通过：Python 3.12 + mcp 2.2.0，实际本地子进程 STDIO initialize/list_tools/call_tool；五项工具、成功检索响应和安全错误响应均可读。后端为明确标识的 fake service，此结果只证明协议包装，不证明真实 RAG/Codex 问答。复现：在该提交工作树安装 SDK 后执行 `python -c "from tests.test_rag_mcp import protocol_probe; protocol_probe()"`。实际输出为 `real-mcp-stdio: PASS (initialize/list_tools/call_tool + safe failure)`。

原指南将 mcpServers JSON 当作 Codex 配置的问题已修正为原生 `codex mcp add` 命令；JSON 仅作为其它兼容宿主的示例。MCP SDK 2.x 的 MCPServer 路径已实际验证。安装环境使用用户临时隔离目录，最终可分发安装包/真实服务仍待 C2。

另一个独立探针证实 Docling 导入成功退出，`-X importtime` 记录累计 66.9 秒：transformers 累计30.67秒、torch累计15.22秒。此前60秒无最终输出不能作为卡死证据；后台原生异常暂不能复现为必然故障。后续采用前台可持续观察会话进行转换，不据此重装全栈。

## 真实依赖与核心生命周期探针

Docling 单页探针在沙箱中明确失败于 Hugging Face 权重下载：`httpx.ConnectError / WinError 10013`，随后 `LocalEntryNotFoundError`。在用户宿主环境以禁用隐式 token 的公共模型下载复跑成功；Khalid 物理页 5 返回 `ConversionStatus.SUCCESS`，首次权重下载与转换合计约 148.9 秒。仅下载模型，原文解析在本地。成功状态不等于表格准确：原始配置把多列厚度、IEC 值合并进单个单元格，因此 RG02 保持 pending，并继续验证 TableFormer 单元格匹配选项。

FastEmbed 0.8.0 的 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 已在用户宿主以两条明确合成的中/英文短句实际生成两个 384 维向量；公开模型缓存约 252 MB。此探针只证明模型可运行，不证明实际文献检索质量。

设计者从不可变提交 `fc3508c49f9a908ec5b617b445bbe9fb1d140aca` 的归档运行真实 FastEmbed、Qdrant 和 LlamaIndex 生命周期探针。一个合成 TXT 首次导入及搜索成功；同实例重复导入失败，成功文档被标记为 failed，实际 indexed_document_count=0 却 index_status=ready；非法 year_min 对象泄漏 SQLite ProgrammingError。详细 JSON 位于忽略目录 `.local/rag-acceptance/core-behavior-fc3508c/results.json`。这些问题已直接交回 Terra 修正，不能用首次成功代替幂等性验收。

修正后 `0c4503b` 和新指纹提交 `7445a67` 的非 editable 安装包均通过 `acceptance/probe_rag_lifecycle.py` 的 18 项检查：同实例重复导入、数量不增长、成功状态、非法输入、范围筛选、修订与旧版本检索、旧 context/源文件保留、搜索及导入拒绝不匹配模型。输入仅为合成 TXT。RAG 验收 venv 隔离了应用包，但共享本机重型依赖；补齐 MCP 2.2.0 声明依赖后 `pip check` 通过，不能将它描述为全依赖隔离安装。

另建不共享系统依赖的 venv，对 `0c4503b` wheel 运行原封不动的 `acceptance/probe_d2_installed.py`，15/15 检查通过，包括真实输出文件、三语报告、冻结重导出和禁网 fixture 流程。后续 `586cadd` / `7445a67` 仅改 RAG 模块和 README，不改 D2 产品模块。

## PDF 表格配置与真实 MCP 接线

设计者使用 Docling 公开的 `TableStructureOptions(do_cell_matching=False)` 对 Khalid 物理页 5 复验，默认 ACCURATE 模式保留。转换 69.9 秒（不含 Python 模块导入）；原本错位的八列表头、厚度、IEC 数值、na 及上标均与可见原页一致，脚注保留为紧邻文本。此结果只覆盖抽查单页；整篇与全库尚在验证。

真实服务 MCP 探针发现 SDK 2.2.0 将同步工具运行到工作线程，触发主线程创建的 SQLite 连接归属错误。独立最小复现得到 `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`。fake 协议测试未覆盖该问题。Luna 正在修正 SDK handler 的调用线程，真实服务与宿主验收继续 pending。

`fa18714` 安装包已独立通过 21/21 生命周期与故障边界检查；新增检查覆盖 Qdrant 占用、向量集合缺失，禁止伪装为纯关键词成功。五个 MCP handler 改为同线程 async wrapper 后，真实 SQLite/FastEmbed 合成库的 SDK initialize/list/status/search/context/document/非法过滤器探针全部通过，详细结果见 `.local/rag-acceptance/mcp-fa18714-synthetic.json`。

Codex CLI 0.153.4 实际运行 `gpt-5.6-luna`、`--ephemeral --ignore-user-config --sandbox read-only`，使用本次显式 aem_rag STDIO 配置与现有 ChatGPT 登录，实际调用 get_library_status 一次，返回 document_count=1/version_count=2/indexed_document_count=1，exit 0。临时宿主任务 ID `01a08974-ac8f-7780-b77d-20f00675c291`，最终文本在 `.local/rag-acceptance/codex-luna-status.txt`。这证明订阅身份与宿主接线，仅使用合成库；真实文献问答仍 pending。

## 可见页面定位修正

`7445a67` 整篇 Khalid 导入产生 410 条证据，其中 92 条 bbox 经 Docling 页面边界裁剪后为零面积；包含旧版页码“7 of 18”和页面外旧排版文字。详情保存在 `.local/rag-acceptance/real-7445a67/zero-area-audit.json`。设计者暂停了该样本运行，该库不能作为完成交付。v3 仅纳入存在于物理页且有非零面积 bbox 的 provenance，排除明确页眉页脚，并记录剔除数量及 partial coverage。在新库重建，旧失败验收库保留用于追溯。

v3 首篇实际解析 603.8 秒，返回 262 个有效布局块、17 页、剔除 92 个无可见定位块；模型/检索组件加载另耗 46.55 秒。向量化及其余样本仍在运行。这些环境实测耗时不能被描述为秒级全库导入。

首篇 318 条证据向量化耗时 248.5 秒；第二篇 Clemens 33 页解析 605.62 秒、1,041 条证据向量化 473.27 秒。两篇合计 1,359 条证据无零面积定位，五组已知原文均在对应物理页存在；这仅是源内容覆盖审计，不是检索评分。第三篇长综述仍在运行。

## 表格上下文与运行环境后续检查点

v3 的表格后紧邻一条重复标题，默认 after=1 因而未带出真正脚注。初次修复 `e30d4f8` 比较了错误字段，设计者拒绝接受；`3634051` 改为比较相邻文本与表格 caption。设计者从不可变提交归档独立执行 `acceptance/probe_rag_real_context.py`，只读备份真实 SQLite、不开原 Qdrant，10/10 通过：物理页 5、八列对应、PI-15 为 na 而非零、PI-20 为 2.35 a、mmol/g 单位、presumably hydroxide 脚注、同文档版本、零扩展和非法窗口边界。结果在 `.local/rag-acceptance/context-3634051.json`。

`fdde388` 修正 CLI 默认 Windows 输出编码，防止中文 JSON 在没有 PYTHONIOENCODING 时被误报为非法输入。`0f17bfa` 仅按文本长度安排嵌入批次、恢复原 evidence 映射；实现者实际向量对照 max_abs_diff=0。Luna 的独立合成基准 32 条文本原顺序 24.177 秒、按长度排序 14.282 秒，不据此声称真实整库加速比例。parser/chunk/model 指纹均未改变；既有三篇处理结果可复用。

固定应用检查点 `ed83faca4df1d243d8ab934dee076b191670549c` 从 git archive 构建，wheel SHA256 为 ccef6727df9993687733f7254552261c76f0c63f0adcb3199e7c2338909ba03d。项目内 `.local/rag-runtime/venv` 正在安装该非 editable 包；安装后检查与真实文献宿主验收尚未完成。

该长期 venv 安装完成，pip check 通过；21/21 生命周期检查、10/10 真实表格检查和默认 Windows UTF-8 CLI 检查通过，安装模块哈希与 ed83fac 归档一致。三篇样本总计 2936.94 秒，102 页、2240 条证据、3/3 indexed、failed=0。安装包真实 MCP initialize/list/status/search/context/document/安全错误通过；中文宽泛查询命中英文交联综述。

## 首轮真实宿主与检索失败记录

Codex CLI / gpt-5.6-luna 使用现有 ChatGPT 登录运行真实样本库，共六次实际只读 MCP 调用。宿主任务 `01a08999-d23c-7191-b814-e92e6a082909`。两问得到回答，但独立逐字引用检查为 6/7：一条 Markdown 表格引文压缩了空格，不是原样子串；缺失值回答开头的“是”与“未提供数据”矛盾。因此 RG05 尚未通过。完整首次 trace/answer/verification 保存于忽略目录 `.local/rag-acceptance/host-run-01`。Luna 已加强不含具体论文答案的通用 MCP 引用、缺失值和直接证据指导，待复验。

首次冻结 v2 诊断在三篇样本上执行：3/18，英语 3/6、中文 0/6、日文 0/6；过滤与上下文边界通过。原定 23 篇数量检查当然未通过，该样本分数不能代替全库评分；在较小语料上已明显未达到检索质量门槛，先诊断后续改进。结果在 `.local/rag-acceptance/retrieval-sample-v2-first.json`。对两个目标段落重新嵌入与原存储向量的 cosine 均约 0.9999999，排除 evidence ID/向量错配；中文纯向量目标排名分别为 55 和 797。短标题、参考文献、长段截断及现用句子模型的检索效果仍须处理。不得宣称多语 RAG 已通过。

## 查询规划与未见问题（进行中）

新候选为官方 intfloat/multilingual-e5-small ONNX，MIT、384 维、512 token，FastEmbed 的公开 custom model 注册方式，query:/passage: 双前缀。已下载官方 snapshot 614241f622f53c4eeff9890bdc4f31cfecc418b3。同一 2240 条真实证据的独立候选编码为 367.5 秒（约 6.1 分钟），原配置三篇向量化合计约 21.5 分钟；模型和批次排序均有变化，不能将全部加速归因于模型。

候选直接原问纯向量诊断仍失败：5/18，仅英语 5/6；中文和日文均 0/6。这不是可接受的直接跨语言检索能力。进一步按用户实际 Codex 路径测试宿主查询规划：由 gpt-5.6-luna 接收原问和文献目录，生成英文检索式及仅在明确点名论文时使用的 DOI 过滤，没有给参考答案或目标页。实际规划任务 01a089b3-3831-7eb0-8d90-2666d52176eb；规划输入、输出、完整 trace 在忽略目录的 query-planning*/query-plans-luna-v1*。

三篇样本、这些规划后的查询：候选 E5 + 未改参数的原混合规则 18/18；候选纯向量 15/18，原 MiniLM 实际服务 12/18。这里只是选择实现方案的旧题回归诊断：三语同义问题在同一规划批次中出现，不能据此声称独立的跨语言泛化。正式验证将按语言分开生成查询，原问与生成式共同归档，并在23篇语料上保留同样的已知证据组命中门槛。直接跨语言分数单独记录，不能混作宿主规划路径的成绩。调用模型负责查询规划，本地 RAG 不新增生成模型调用器、API key 依赖或硬编码翻译字典。

已从另外两篇原PDF渲染核对并冻结6个未见问题：Molecular Modeling 综述物理页4的相分离形态及控制因素；Radiation-Grafted 综述物理页11的预辐照活性物种及有氧路线加热。每组中英日三问，top_k=8，至少5/6命中且每种语言至少1/2。问题、支持词和页码在 evaluation-holdout-v1.json，SHA256=37bde4433269e2945449faa7c52e69b435a7c19acd684e2e20d0eec91265e1fb。原页PNG在 holdout-images；实现者未接触该集合，尚未执行候选检索。

## 并行解析检查点

b972ac43ea3720cc2384628feec4f27c1b0e3f52 安装包 SHA256=7e8462e32bbec0a311c8f75938255819ef5e0f9ec6904f04eef428215c213f2d。设计者安装后独立检查 prepare 计数/重复复用、无evidence、无Qdrant、跨workspace复制缓存后真实嵌入入库，四项通过。剩余20篇按页数分为242页和240页的两组，各10篇；两个独立workspace的真实prepare正在运行，不争用同一Qdrant。完成解析不等于完成索引。

### 模型适配与正式查询输入检查

Luna 用同一官方 E5 small 缓存的 AutoTokenizer + ONNX Runtime、attention-mask mean pooling 与 L2 normalize，对照 FastEmbed 的六个合成中/英/日 query/passage。token 数为16/17/17/28/28/25，UNK比例全部为0，向量最大绝对差≤2.4e-08，cosine约1。该结果排除本探针覆盖的分词、pooling与ONNX适配错误；不能把它当作真实语料召回验收。

正式查询规划分别由三个 Codex/Luna 宿主实例执行，每次只提供一种语言的8个问题和文献题名/DOI等元数据，不提供答案、支持词或页码；trace均无工具调用，输出8个唯一问题ID。中文任务01a089bc-943f-72a0-a909-3d3e52f9b8e8、英文01a089bc-9490-73a0-9082-84bf663c3c64、日文01a089bc-96d6-7843-8fcc-67b37fe3b9d1。输出SHA256依次为7d6ab436c2dd2f714eaed8c34d0bbbc36dc03279446587ae011dc7b158e6449a、b7ba6bf65823a28408d1d473cf799fb52a2d11432766182887e41b9863346878、50236474cb271b9654bd45bb9d8a7523cbff8dfaf33440168aed29e6d3db6b30。合并文件query-plans-formal-v1.json仅用于按已冻结输入执行检索，尚无正式全库分数。

两条原解析队列启动后，又使用两个独立workspace提前解析各队列后五篇，并在完成后原子复制有效缓存给原队列。原队列到达这些文件时直接复用。四进程只处理解析缓存，不同时写同一Qdrant；先前完成的解析不作废。

### E5 安装包与迁移检查点

不可变实现 d6ff98a184fcefa12858c28fc9ba0d84aa55bd3e 的 wheel SHA256 为 4f34e3e56a7198e7f549af6142283b77769002f2d39b7c45507099085c86fc46，在独立应用 venv 非 editable 安装。设计者生命周期21/21与新增迁移21/21通过；后者使用已有合成两版本库，覆盖初始化安全错误、写入后故障回滚、旧索引仍可检索、临时集合清理、query/passage前缀、全部旧版本迁移、原数据/文件/ID不变、活动模型状态及重开读取。结果分别在 lifecycle-d6ff98a/results.json 和 migration-d6ff98a/result.json。真实三篇向量重建正在进行，尚无该步骤成功声明。
