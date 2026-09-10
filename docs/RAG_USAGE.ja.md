# ローカル RAG MCP

これはローカル STDIO MCP アダプターです。`research_harness.rag.RagLibrary` を呼び出すだけで、Codex の認証情報を読み取らず、生成モデルを呼び出さず、HTTP/UI も提供しません。

## 最短のローカル手順

[RAG_RUNTIME.md](RAG_RUNTIME.md) に従ってキャッシュを設定し `.[rag-mcp]` を導入します。長時間の CLI 導入を終えてから、同じ workspace に MCP を登録してください。

```powershell
$env:RAG_MODEL_CACHE = "$PWD\.local\rag-runtime\models"
$env:HF_HOME = "$PWD\.local\rag-runtime\huggingface"
python -m pip install ".[rag-mcp]"
python -m research_harness.rag --workspace C:\data\rag-workspace import C:\data\catalog.json
python -m research_harness.rag --workspace C:\data\rag-workspace search "架橋 膨潤"
codex mcp add research-harness-rag -- C:\path\to\.venv\Scripts\python.exe -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

範囲は [RAG_STAGE.md](RAG_STAGE.md) を参照してください。生成モデル API はこの段階では契約のみで、実23文献の受入は進行中です。

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

MCP は単一プロセスの逐次サービスです。初回のモデル読み込みや導入処理中はプロセスがブロックされます。長時間の導入は CLI を使い、同じ workspace を MCP が開いている間に CLI 導入を並行実行しないでください。

コアサービスで資料を導入済みの場合は `real_service_probe(python_executable, workspace, catalog)` で実 STDIO 検査を実行できます。導入処理は行いません。fake プロトコルテストとは別の証拠として記録してください。
