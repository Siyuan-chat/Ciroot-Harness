<p align="center">
  <img src="assets/ciroot-harness-logo.png" alt="CirootHarness logo" width="220">
</p>

<h1 align="center">CirootHarness</h1>

<p align="center">
  <strong>面向专利与科学文献的可审计 AI 调查框架。</strong><br>
  把研究问题转换为版本化、证据可追溯、可人工复核的调查报告。
</p>

<p align="center">
  中文 · <a href="README.md">English</a> · <a href="README.ja.md">日本語</a>
</p>

<p align="center">
  <a href="https://github.com/Siyuan-chat/autoSearch-Harness/actions/workflows/ci.yml"><img src="https://github.com/Siyuan-chat/autoSearch-Harness/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="Apache-2.0">
  <img src="https://img.shields.io/badge/status-desktop%20preview-orange" alt="Desktop preview">
</p>

<p align="center">
  <a href="https://github.com/Siyuan-chat/autoSearch-Harness/releases">下载 Windows 预览版</a> ·
  <a href="#运行离线-demo">运行离线 Demo</a> ·
  <a href="#架构">架构</a> ·
  <a href="docs/DEVELOPMENT_STATUS.md">工程状态</a>
</p>

CirootHarness 是一个本地优先的文献／专利调查 harness。它的目标不只是“生成一个答案”，而是让一次调查结束后仍能检查：当时冻结了什么需求、调用了哪些来源、使用了哪个文档版本、结论对应哪段证据、哪些问题进入了人工复核，以及本轮究竟是完成、部分完成还是失败。

> **项目原则：** `partial` 不等于 `completed`；引用只有能够回到原文位置时才算证据；目标设计不能被包装成已经实现的功能。

## 为什么做 CirootHarness？

很多 research agent 优先优化最终答案的流畅度。CirootHarness 优先解决另一个问题：**AI 调查结果在生成之后还能不能被审计。**

| 问题 | CirootHarness 的处理方式 |
| --- | --- |
| 需求在调查过程中漂移 | 版本化 `ResearchSpec` + 冻结运行输入 |
| 结论无法追溯 | Evidence ID 绑定 document version 与 locator |
| 引用幻觉 | 引文归属、quote 与原文匹配检查 |
| 检索失败被悄悄忽略 | 显式 `complete` / `partial` / `failed` / `unsupported` |
| 模糊结论 | 持久化 human-review issue 与决定历史 |
| 私有资料 | local-first 文档存储与 RAG 路径 |
| 难以复现 | 冻结输入、结构化运行状态与持久产物 |

## 目前已经能做什么

CirootHarness 目前仍是持续开发中的公开预览版，不是已经完成的生产级研究服务。

| 能力 | 当前状态 |
| --- | --- |
| Windows 桌面预览版 | 已提供 portable prerelease；原生 WebView2 交互尚未完整验收 |
| 本地工作区与文献库 | 可创建 workspace/library；导入可提取文字的 PDF 和 UTF-8 TXT |
| 本地基础文本检索 | 桌面预览版可用 |
| 离线调查 Demo | 使用确定性合成来源；运行 LangGraph、SQLite、引用检查 |
| 多语言报告 | fixture 流程支持中、英、日输出 |
| 本地 RAG | Docling/FastEmbed/Qdrant 路径已有验收记录 |
| OA 文献采集 | OpenAlex 检索与 OA PDF 采集模块 |
| Investigation service | 已实现验收范围内的 evidence/report/review/monitoring primitives |
| 有界论文案例 | P3 已通过新 PDF 入库、RAG、报告导出与重开检查 |
| Live 专利工作流 | 仍在推进，不能把目标设计当成已验收端到端能力 |

详细阶段边界统一放在 [工程状态](docs/DEVELOPMENT_STATUS.md)。

## 快速开始

### 1. Windows 桌面预览版

从 [GitHub Releases](https://github.com/Siyuan-chat/autoSearch-Harness/releases) 下载当前 portable ZIP，**完整解压** `ResearchHarnessGUI` 文件夹，然后运行：

```text
ResearchHarnessGUI.exe
```

窗口品牌名称为 **CirootHarness**；EXE 文件名暂时保留旧技术名称以保持兼容。

发布包不附带作者本机的私有文献、模型缓存或 API 密钥。首次启动可以创建工作区和文献库，导入可提取文字的 PDF / UTF-8 TXT，并进行本地基础文本检索。当前 GUI 边界见 [中文图形界面使用说明](docs/GUI_QUICKSTART.zh-CN.md)。

### 2. 运行离线 Demo

需要 Python 3.11+。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .
.venv\Scripts\rh demo --workspace .local\demo
.venv\Scripts\rh status --workspace .local\demo
```

macOS / Linux 使用 `.venv/bin/python` 与 `.venv/bin/rh`。

Demo 本身离线运行、不需要 API key。它会生成合成候选、已核查 findings、人工复核问题、HTML/Markdown 报告、规范 JSON 和 review CSV。

**合成 Demo 数据与真实科学证据始终明确分开。**

## 架构

目标系统从研究问题开始，经过规格化、检索、证据提取、核查、人工复核与报告生成。

![CirootHarness architecture](docs/diagrams/harness-overview.png)

这张图描述的是**整体设计**。已经实现／已经验收的范围单独维护，避免把规划组件误写成现有能力。

参见 [整体设计](docs/SYSTEM_DESIGN.md)、[架构说明](docs/ARCHITECTURE.md) 与 [工程状态](docs/DEVELOPMENT_STATUS.md)。

## 本地 RAG

```powershell
.venv\Scripts\python -m pip install ".[rag-mcp]"
.venv\Scripts\python -m research_harness.rag --workspace .local\aem-rag status
```

本地 RAG 只读取明确配置的 catalog，不读取 Codex 凭据，也不会自行调用生成模型。

参见 [RAG 使用说明](docs/RAG_USAGE.zh-CN.md)、[运行时说明](docs/RAG_RUNTIME.md)、[阶段边界](docs/RAG_STAGE.md)、[验收记录](docs/RAG_ACCEPTANCE.md)。

## OA 文献采集

`literature` 模块负责 OpenAlex 检索与 OA PDF 采集；它与科学筛选、RAG 刻意分离。

```powershell
.venv\Scripts\python -m pip install ".[literature]"
.venv\Scripts\python -m research_harness.literature search --config examples\aem_oa_reviews.json --output .local\aem-candidates.json
.venv\Scripts\python -m research_harness.literature download --manifest examples\aem_oa_manifest.json --output .local\aem-pdfs --limit 23
```

## Investigation service

调查层已经包含 host-agent 角色、source-query 记账、证据记录、冻结报告、人工复核历史和专利监测 primitives。

```powershell
.venv\Scripts\python -m pip install ".[investigation]"
.venv\Scripts\rh investigate --workspace .local\investigation doctor
```

参见 [使用说明](docs/INVESTIGATION_USAGE.zh-CN.md)、[实现记录](docs/D19_P1_IMPLEMENTATION.md)、[验收边界](docs/D19_P1_ACCEPTANCE.md)。

## Demo 与公开展示

公开 Demo 应在很短时间内证明四件事：

1. 一个自然语言问题如何变成冻结的研究规格；
2. 系统实际搜索了什么、哪些来源成功或失败；
3. 报告主张如何回到 evidence 与原文位置；
4. 已验证结论与未解决人工问题如何被明确分开。

截图命名、60–90 秒视频脚本、README hero 资产和真实性规则见 [Demo 展示指南](docs/DEMO_SHOWCASE.md)。

## 当前边界

公开预览版**不代表**以下能力已经生产可用：

- live 模型 + live source API 的完整端到端调查；
- 完整专利族检索覆盖；
- 扫描版 PDF OCR；
- 桌面预览版中的跨库语义检索；
- 无人值守的生产监控；
- 法律意见、FTO 意见或可专利性结论。

API key、私有原文、运行工作区和模型缓存应保持在 Git 仓库之外。

## 文档入口

- [工程状态](docs/DEVELOPMENT_STATUS.md)
- [整体设计](docs/SYSTEM_DESIGN.md)
- [架构](docs/ARCHITECTURE.md)
- [PRD](docs/PRD.md)
- [数据／适配器契约](docs/CONTRACTS.md)
- [框架验收](docs/FRAMEWORK_ACCEPTANCE.md)
- [RAG 验收](docs/RAG_ACCEPTANCE.md)
- [调查方案](docs/INVESTIGATION_EXPERIMENT_PLAN.md)
- [中文用户指南](docs/USER_GUIDE.zh-CN.md)

## 引用

如果 CirootHarness 对科研或技术工作有帮助，请使用仓库中的 [`CITATION.cff`](CITATION.cff) 进行引用。

## License

本项目采用 [Apache License 2.0](LICENSE)。
