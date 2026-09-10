# 本地 RAG MCP

这是一个本地 STDIO MCP 适配器。它只调用 `research_harness.rag.RagLibrary`，不读取 Codex 凭据、不调用生成模型，也不提供 HTTP 或 GUI。

## 最短本地顺序

按 [RAG_RUNTIME.md](RAG_RUNTIME.md) 设置缓存并安装到同一个虚拟环境；先完成长时间 CLI 导入，再为同一 workspace 注册 MCP。`--env` 会为 Codex 启动的服务持久保存缓存位置，仅设置当前 shell 变量并不够：

```powershell
python -m venv .venv
$py = (Resolve-Path .venv\Scripts\python.exe)
$repo = (Get-Location).Path
$modelCache = Join-Path $repo ".local\rag-runtime\models"
$hfHome = Join-Path $repo ".local\rag-runtime\huggingface"
New-Item -ItemType Directory -Force -Path $modelCache, $hfHome | Out-Null
$modelCache = (Resolve-Path $modelCache).Path
$hfHome = (Resolve-Path $hfHome).Path
$env:RAG_MODEL_CACHE = $modelCache
$env:HF_HOME = $hfHome
& $py -m pip install ".[rag-mcp]"
& $py -m research_harness.rag --workspace C:\data\rag-workspace import C:\data\catalog.json
& $py -m research_harness.rag --workspace C:\data\rag-workspace search "crosslinking methods reduce membrane swelling"
codex mcp add research-harness-rag --env "RAG_MODEL_CACHE=$modelCache" --env "HF_HOME=$hfHome" -- $py -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

范围见 [RAG_STAGE.md](RAG_STAGE.md) 和[独立验收记录](RAG_ACCEPTANCE.md)。生成模型 API 本阶段仅有契约。

`prepare` 只创建或复用解析缓存，不创建证据或向量；`rebuild` 只从既有证据迁移向量，不重新解析原文：`& $py -m research_harness.rag --workspace C:\data\rag-workspace rebuild`。这两项长操作执行时，MCP 不得打开同一 workspace。用户可在 Codex 中用中文或日文提问；宿主可先规划英文检索式，再调用本地检索。

准备一个可写的 workspace 和 catalog。catalog 的 `records[].file` 是相对 catalog 目录的 PDF/TXT 路径，适配器会拒绝越出 catalog 目录的路径；原目录保持只读。启动参数固定 workspace 与 catalog，工具不能改路径。

首次启动模型可能超过普通工具超时。注册后，在 `~/.codex/config.toml` 已有的 `[mcp_servers.research-harness-rag]` 段内加入原生 Codex 配置（不要新建第二个同名段）：

```toml
startup_timeout_sec = 120
tool_timeout_sec = 600
```

`examples/rag-mcp.windows.json` 是接受该 JSON 格式的其它 MCP 宿主的配置示例；也可以直接运行：

```powershell
& $py -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

提供五个工具：`import_library(limit?)`、`search_evidence(query, top_k?, filters?)`、`get_evidence_context(evidence_id, before?, after?)`、`get_document(document_id)`、`get_library_status()`。导入是唯一写工具；其它四项为只读。失败返回 `{ "error": { "code", "message" } }`，不会返回底层异常或秘密。

支持边界由 RagLibrary 的实际解析器、Embedding、索引和 coverage 状态决定。协议测试使用 fake service；它不代表真实 PDF、三语检索或 Codex 宿主验收已经通过。

MCP 是单进程串行服务；首次加载模型或导入资料会阻塞该进程。长时间导入建议使用 CLI，CLI 导入与 MCP 打开同一 workspace 时不要并行运行。

当语料为英文而问题使用中文或日文时，宿主模型可根据原问题生成简洁英文检索式，同时保留原问题用于回答；不得使用硬编码翻译表，也不得猜测事实或数值。若论文标题已完整且唯一，应使用 DOI 或文档过滤器，不要把标题混入主题检索式。先找直接证据，再用 context 补读。直接中日文跨语向量检索尚未验收，不能据此声称通过。

核心服务已导入资料后，可用 `real_service_probe(python_executable, workspace, catalog)` 运行真实 STDIO 检查；它不会执行导入。该探针与 fake 协议测试的证据必须分开记录。
