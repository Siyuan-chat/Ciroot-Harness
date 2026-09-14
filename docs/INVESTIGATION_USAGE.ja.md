# オフライン調査ホスト

調査用依存関係をインストール後、ローカルの
`InvestigationService` を `rh investigate ...` から呼び出します。

```powershell
rh investigate --workspace .local/d19-workspace doctor
rh investigate --workspace .local/d19-workspace start --spec spec.json --runtime runtime.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
```

MCP は `python -m research_harness.investigation_mcp --workspace PATH` で起動します。P1 は明示した synthetic/replay を使うオフライン host モード בלבדで、実際の情報源、生成モデル API、OS スケジューラは呼び出しません。指定された task version を提出し、欠測値、不確実性、原文の連続引用と位置情報を保持してください。初回処理は単一プロセスを停止させることがあるため、MCP が同じライブラリを開いている間は CLI 書き込みを並行実行しないでください。
