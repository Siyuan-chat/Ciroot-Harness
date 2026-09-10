# Research Harness

中文 · [English](README.md) · [日本語](README.ja.md)

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

后续首个案例为聚合物设计。[案例草案](examples/polymer-design.draft.json) 仍有待定需求，不是可运行的科学案例。真实 API 接入及案例／demo 验收后再发布 GitHub；当前没有科学案例或公开发布验收结论。

密钥、私有原文和运行工作区不要提交 Git。包内演示仅含合成材料。产品调查由用户手动启动，没有默认后台定时任务。

## 开放文献采集

## 本地 RAG（D18，进行中）

```powershell
.venv\Scripts\python -m pip install ".[rag-mcp]"
.venv\Scripts\python -m research_harness.rag --workspace .local\aem-rag status
```

本地 RAG 只读取配置的 catalog，不读取 Codex 凭据，也不调用生成模型。JSON 操作为 `import`、`search`、`context`、`document`、`status`。真实 PDF 验收仍在进行。

`literature` 是独立的 OpenAlex 检索和 OA PDF 采集模块，不是 RAG 或科学筛选。安装校验器后，可在提供时使用已核验的 23 项清单：

```powershell
.venv\Scripts\python -m pip install ".[literature]"
.venv\Scripts\python -m research_harness.literature search --config examples\aem_oa_reviews.json --output .local\aem-candidates.json
.venv\Scripts\python -m research_harness.literature download --manifest examples\aem_oa_manifest.json --output .local\aem-pdfs --limit 23
```

`anonymous: true` 明确执行无密钥查询；否则设置 `OPENALEX_API_KEY`。AEM 检索示例使用 `review_only: false`，因为 OpenAlex type 标签会遗漏综述，调用者须筛选记录。下载器校验可读性、身份和记录可选的 `expected_min_pages`；不足时返回 `partial` 和退出码 4。
