# Research Harness

中文 · [English](README.md) · [日本語](README.ja.md)

## CirootHarness Windows 桌面版

下载 GitHub Releases 中的 Windows ZIP，**解压整个 `ResearchHarnessGUI` 文件夹**，运行其中的 `ResearchHarnessGUI.exe`。程序窗口名称为 CirootHarness；EXE 文件名是兼容保留的技术名称。[中文图形界面使用说明](docs/GUI_QUICKSTART.zh-CN.md)介绍首次启动、工作区、文献库、Agent 对话及本地资料配置。软件本身不附带本机的 23 篇文献、模型缓存、API 密钥或研究工作区。

当前发布的是本地桌面候选：可在空白工作区创建文献库，导入可提取文字的 PDF 或 UTF-8 TXT，并进行本地基础文本检索。跨库检索、收费模型端到端调查及原生 WebView2 全流程尚未完成验收。运行真实 API 可能产生费用，需用户自行配置凭据并明确执行。具体边界见[图形界面使用说明](docs/GUI_QUICKSTART.zh-CN.md)。

**2026-09-16 进展：** P3 有界论文案例已通过独立验收，包含新 PDF 的 Docling/RAG 入库、中文双报告正文、标准导出与重开；检索覆盖仍为 partial。P4 单专利族阶段已完成范围设计，OPS 注册审批 pending。[P3 验收](docs/D19_P3_LOOP2_ACCEPTANCE.md) · [P4 计划](docs/D19_P4_PLAN.md) · [替代方案](docs/D19_P4_FALLBACK.md)。

[整体设计文档](docs/SYSTEM_DESIGN.md) · [总架构图](docs/diagrams/harness-overview.svg) · [D19实验方案](docs/INVESTIGATION_EXPERIMENT_PLAN.md)。设计覆盖一次性调查、企业监测与人工分流；已实现能力另有明确状态。

本地文献／专利调查框架。目标流程：自然语言需求 → 版本化 JSON → 检索 → 与冻结参照库比较 → 人工判断与报告。

**D2 合成夹具框架已于 2026-09-09 通过独立验收。** 见[验收报告](docs/FRAMEWORK_ACCEPTANCE.md)。demo 使用合成文本和本地来源／模型函数，实际运行 LangGraph、SQLite、引用核查及中英日报告；无需 API 密钥，不调用外部 API。

## 快速开始

需要 Python 3.11+，在 Windows 源码目录执行：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .
.venv\Scripts\rh demo --workspace .local\demo
.venv\Scripts\rh status --workspace .local\demo
```

安装会下载声明的依赖，demo 本身离线运行。macOS/Linux 对应 `.venv/bin/python`、`.venv/bin/rh`；当前独立运行验收针对 Windows。

demo 生成两条合成候选、核查后的判断、一条人工问题、三份 HTML、三份 Markdown、规范 JSON 和人工清单 CSV。打开命令返回的报告目录即可阅读。

## 当前能力

- ResearchSpec 校验、手改后的自动修订、冻结运行输入。
- 本地文本原文与证据，参照快照和新发现分离。
- 可替换的 fixture 来源／模型函数与最小 LangGraph 流程。
- 引用归属／原文匹配、持久人工决定、候选上限和明确的部分完成／失败状态。
- 供未来 GUI 调用的共享 Python 服务、结构化结果、安全错误、产物引用和进度回调。

真实模型／来源 API、OpenAlex/EPO、生产向量 RAG、PDF/OCR、独立 chat、恢复和 GUI **尚未接入 D2**。安装可选依赖不会自动启用这些功能。未支持的 live/chat 路径明确拒绝；`lexical_test_only` 仅保留测试兼容。当前由宿主助手澄清需求并整理 JSON。

[中文指南](docs/USER_GUIDE.zh-CN.md) · [当前范围](docs/SCOPE_AUDIT.md) · [数据／适配器契约](docs/CONTRACTS.md) · [验收 K01–K07](docs/ACCEPTANCE.md) · [需求](docs/PRD.md) · [架构](docs/ARCHITECTURE.md) · [决策](docs/DECISIONS.md)

后续首个案例为聚合物设计。[案例草案](examples/polymer-design.draft.json) 仍有待定需求，不是可运行的科学案例。P3 有界论文案例已验收，更广泛科学评价仍待完成；桌面候选发布不代表科研案例或全部 GUI 门槛通过。

密钥、私有原文和运行工作区不要提交 Git。包内演示仅含合成材料。产品调查由用户手动启动，没有默认后台定时任务。

## 本地 RAG（D18）

```powershell
.venv\Scripts\python -m pip install ".[rag-mcp]"
.venv\Scripts\python -m research_harness.rag --workspace .local\aem-rag status
```

本地 RAG 只读取配置的 catalog，不读取 Codex 凭据，也不调用生成模型。CLI 操作为 `prepare`、`import`、`search`、`context`、`document`、`status`、`rebuild`；`prepare` 只缓存解析，`rebuild` 只从既有证据迁移向量。参见[本地使用指南](docs/RAG_USAGE.zh-CN.md)、[运行时说明](docs/RAG_RUNTIME.md)、[阶段边界](docs/RAG_STAGE.md)和[独立验收记录](docs/RAG_ACCEPTANCE.md)。

## 开放文献采集

`literature` 是独立的 OpenAlex 检索和 OA PDF 采集模块，不是 RAG 或科学筛选。安装校验器后，可在提供时使用已核验的 23 项清单：

```powershell
.venv\Scripts\python -m pip install ".[literature]"
.venv\Scripts\python -m research_harness.literature search --config examples\aem_oa_reviews.json --output .local\aem-candidates.json
.venv\Scripts\python -m research_harness.literature download --manifest examples\aem_oa_manifest.json --output .local\aem-pdfs --limit 23
```

`anonymous: true` 明确执行无密钥查询；否则设置 `OPENALEX_API_KEY`。AEM 检索示例使用 `review_only: false`，因为 OpenAlex type 标签会遗漏综述，调用者须筛选记录。下载器校验可读性、身份和记录可选的 `expected_min_pages`；不足时返回 `partial` 和退出码 4。

## 离线调查与监测（D19 P1）

调查服务提供八个宿主 agent 角色、查询与重试记账、PDF/XML/文本证据、冻结的技术调查报告与文献综述，以及保留规则版本和人工决定历史的专利监测。离线夹具支持中文、英文、日文产物。

```powershell
.venv\Scripts\python -m pip install ".[investigation]"
.venv\Scripts\rh investigate --workspace .local\investigation doctor
```

[使用指南](docs/INVESTIGATION_USAGE.zh-CN.md) · [实现记录](docs/D19_P1_IMPLEMENTATION.md) · [独立验收与边界](docs/D19_P1_ACCEPTANCE.md)。本阶段使用显式合成来源及宿主/replay 结果，不启用真实模型/来源 API 或系统定时任务。D18 本地 RAG 与文献采集模块保持独立。
