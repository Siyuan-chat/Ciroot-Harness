# オフライン調査ホスト

調査用依存関係をインストール後、ローカルの
`InvestigationService` を `rh investigate ...` から呼び出します。

```powershell
rh investigate --workspace .local/d19-workspace doctor
rh investigate --workspace .local/d19-workspace start --spec spec.json --runtime runtime.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
```

MCP は `python -m research_harness.investigation_mcp --workspace PATH` で起動します。P1 は明示した synthetic/replay を使うオフライン host モード בלבדで、実際の情報源、生成モデル API、OS スケジューラは呼び出しません。指定された task version を提出し、欠測値、不確実性、原文の連続引用と位置情報を保持してください。初回処理は単一プロセスを停止させることがあるため、MCP が同じライブラリを開いている間は CLI 書き込みを並行実行しないでください。
監視設定は実行せずに検証し、その後状態を確認できます。

```powershell
rh monitor --workspace .local/d19-workspace validate --profile profile.json --spec monitor.json --runtime runtime.json
rh monitor --workspace .local/d19-workspace status MONITOR_ID
```
完全なオフライン調査の流れは、依存関係（例: `pip install -e .[test,mcp]`）をインストールし、`spec.json` と `runtime.json` を用意して次を実行します。

```powershell
rh investigate --workspace .local/d19-workspace start --spec spec.json --runtime runtime.json
rh investigate --workspace .local/d19-workspace tasks RUN_ID
rh investigate --workspace .local/d19-workspace submit RUN_ID TASK_ID --result result.json --task-version 1
rh investigate --workspace .local/d19-workspace work RUN_ID
rh investigate --workspace .local/d19-workspace resume RUN_ID
rh investigate --workspace .local/d19-workspace report RUN_ID
```

入力は利用者が用意するオフライン JSON と明示した synthetic シナリオです。実際の情報源や生成モデル API は呼び出しません。監視は `run-once` の後に `review` と明示的な `decide` を実行します。

```powershell
rh monitor --workspace .local/d19-workspace run-once MONITOR_ID --scenario cycle.json
rh monitor --workspace .local/d19-workspace review --monitor-id MONITOR_ID
rh monitor --workspace .local/d19-workspace decide ISSUE_ID --decision accept --note note
```
