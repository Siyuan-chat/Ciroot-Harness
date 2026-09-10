# 本地 RAG MCP

这是一个本地 STDIO MCP 适配器。它只调用 `research_harness.rag.RagLibrary`，不读取 Codex 凭据、不调用生成模型，也不提供 HTTP 或 GUI。

先安装项目及 MCP Python SDK（例如项目提供的 `.[rag,mcp]` 可选依赖），然后准备一个可写的 workspace 和 catalog。catalog 的 `records[].file` 是相对 catalog 目录的 PDF/TXT 路径，适配器会拒绝越出 catalog 目录的路径；原目录保持只读。启动参数固定 workspace 与 catalog，工具不能改路径。

在 Codex 中使用 CLI 注册（替换实际路径）：

```powershell
codex mcp add research-harness-rag -- C:\path\to\.venv\Scripts\python.exe -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

`examples/rag-mcp.windows.json` 是接受该 JSON 格式的其它 MCP 宿主的配置示例；也可以直接运行：

```powershell
python -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

提供五个工具：`import_library(limit?)`、`search_evidence(query, top_k?, filters?)`、`get_evidence_context(evidence_id, before?, after?)`、`get_document(document_id)`、`get_library_status()`。导入是唯一写工具；其它四项为只读。失败返回 `{ "error": { "code", "message" } }`，不会返回底层异常或秘密。

支持边界由 RagLibrary 的实际解析器、Embedding、索引和 coverage 状态决定。协议测试使用 fake service；它不代表真实 PDF、三语检索或 Codex 宿主验收已经通过。

核心服务已导入资料后，可用 `real_service_probe(python_executable, workspace, catalog)` 运行真实 STDIO 检查；它不会执行导入。该探针与 fake 协议测试的证据必须分开记录。
