# ローカル RAG MCP

これはローカル STDIO MCP アダプターです。`research_harness.rag.RagLibrary` を呼び出すだけで、Codex の認証情報を読み取らず、生成モデルを呼び出さず、HTTP/UI も提供しません。

プロジェクトと MCP Python SDK（利用可能なら `.[rag,mcp]` オプション依存）をインストールし、書き込み可能な workspace と catalog を用意してください。catalog の `records[].file` は catalog ディレクトリからの相対 PDF/TXT パスです。ディレクトリ外へのパスは拒否され、原資料ディレクトリは読み取り専用です。workspace と catalog は起動時に固定され、ツールから変更できません。

Codex CLI への登録（パスを置き換えてください）：

```powershell
codex mcp add research-harness-rag -- C:\path\to\.venv\Scripts\python.exe -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

`examples/rag-mcp.windows.json` は同形式の JSON を受け付ける他の MCP ホスト向けです。直接起動する場合：

```powershell
python -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

ツールは `import_library(limit?)`、`search_evidence(query, top_k?, filters?)`、`get_evidence_context(evidence_id, before?, after?)`、`get_document(document_id)`、`get_library_status()` の5つです。書き込みは import のみです。失敗時は低レベル例外や秘密を含まない `{ "error": { "code", "message" } }` を返します。

対応する解析器、Embedding、索引、coverage は RagLibrary の実装に依存します。プロトコルテストは明示的な fake service を使うため、実 PDF、多言語検索、Codex ホスト接続の合格を意味しません。
