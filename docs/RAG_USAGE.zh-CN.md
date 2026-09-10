# 本地 RAG MCP

这是一个本地 STDIO MCP 适配器。它只调用 `research_harness.rag.RagLibrary`，不读取 Codex 凭据、不调用生成模型，也不提供 HTTP 或 GUI。

先在 Terra 提供的项目环境安装项目及 MCP Python SDK，然后准备一个可写的 workspace 和 catalog。catalog 的 `records[].file` 必须指向 workspace 外部允许读取的本地 PDF/TXT；启动参数固定 workspace 与 catalog，工具不能改路径。

将 `examples/rag-mcp.windows.json` 复制到宿主 MCP 配置并替换 Python、workspace、catalog 路径。也可以运行：

```powershell
python -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

提供五个工具：`import_library(limit?)`、`search_evidence(query, top_k?, filters?)`、`get_evidence_context(evidence_id, before?, after?)`、`get_document(document_id)`、`get_library_status()`。导入是唯一写工具；其它四项为只读。失败返回 `{ "error": { "code", "message" } }`，不会返回底层异常或秘密。

支持边界由 RagLibrary 的实际解析器、Embedding、索引和 coverage 状态决定。协议测试使用 fake service；它不代表真实 PDF、三语检索或 Codex 宿主验收已经通过。
