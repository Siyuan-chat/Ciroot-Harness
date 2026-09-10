# ローカル RAG MCP

これはローカル STDIO MCP アダプターです。`research_harness.rag.RagLibrary` を呼び出すだけで、Codex の認証情報を読み取らず、生成モデルを呼び出さず、HTTP/UI も提供しません。

## 最短のローカル手順

[RAG_RUNTIME.md](RAG_RUNTIME.md) に従ってキャッシュを設定し、同じ仮想環境に `.[rag-mcp]` を導入します。長時間の CLI 導入を終えてから、同じ workspace に MCP を登録してください。`--env` は Codex が起動するサービスにもキャッシュ場所を永続化します。shell 変数だけでは不十分です。

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

範囲は [RAG_STAGE.md](RAG_STAGE.md) と[独立受入記録](RAG_ACCEPTANCE.md)を参照してください。生成モデル API はこの段階では契約のみです。

`prepare` は parse-cache の作成または再利用だけを行い、evidence や vector を作りません。`rebuild` は原資料を再解析せず既存 evidence から vector だけを移行します：`& $py -m research_harness.rag --workspace C:\data\rag-workspace rebuild`。これらの長時間操作中は、同じ workspace を MCP で開かないでください。Codex では中国語・日本語で質問でき、ホストはローカル検索の前に英語の検索式を計画できます。

検索は dense cosine と BM25 の語彙候補を固定の reciprocal-rank fusion で結合します。BM25 は CJK n-gram と英語の語幹化を含む、filter と同じ token 流を使用します。質問ごとの stopword 表や順位パラメータは設定しません。

書き込み可能な workspace と catalog を用意してください。catalog の `records[].file` は catalog ディレクトリからの相対 PDF/TXT パスです。ディレクトリ外へのパスは拒否され、原資料ディレクトリは読み取り専用です。workspace と catalog は起動時に固定され、ツールから変更できません。

初回のモデル起動は通常のツール timeout を超えることがあります。登録後、`~/.codex/config.toml` の既存 `[mcp_servers.research-harness-rag]` セクション内にこのネイティブ Codex 設定を追加してください（同名の第二セクションは作成しません）。

```toml
startup_timeout_sec = 120
tool_timeout_sec = 600
```

`examples/rag-mcp.windows.json` は同形式の JSON を受け付ける他の MCP ホスト向けです。直接起動する場合：

```powershell
& $py -m research_harness.rag_mcp --workspace C:\data\rag-workspace --catalog C:\data\catalog.json
```

ツールは `import_library(limit?)`、`search_evidence(query, top_k?, filters?)`、`get_evidence_context(evidence_id, before?, after?)`、`get_document(document_id)`、`get_library_status()` の5つです。書き込みは import のみです。失敗時は低レベル例外や秘密を含まない `{ "error": { "code", "message" } }` を返します。

対応する解析器、Embedding、索引、coverage は RagLibrary の実装に依存します。プロトコルテストは明示的な fake service を使うため、実 PDF、多言語検索、Codex ホスト接続の合格を意味しません。

MCP は単一プロセスの逐次サービスです。初回のモデル読み込みや導入処理中はプロセスがブロックされます。長時間の導入は CLI を使い、同じ workspace を MCP が開いている間に CLI 導入を並行実行しないでください。

英語コーパスに対して中国語または日本語で質問する場合、ホストモデルは元の質問を回答に残したまま、簡潔な英語検索式を生成できます。ハードコードした翻訳表や推測した事実・数値は使わないでください。論文タイトルが完全かつ一意に特定できる場合は、タイトルをテーマ検索式に混ぜず DOI または文書フィルターを使います。まず直接証拠を探し、その後 context で補読します。中国語・日本語の直接クロス言語ベクトル検索は未検収であり、合格とは表明できません。

コアサービスで資料を導入済みの場合は `real_service_probe(python_executable, workspace, catalog)` で実 STDIO 検査を実行できます。導入処理は行いません。fake プロトコルテストとは別の証拠として記録してください。
