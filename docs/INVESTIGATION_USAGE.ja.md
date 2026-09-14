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
rh monitor --workspace .local/d19-workspace create --profile profile.json --spec monitor.json --runtime runtime.json --scenario .\examples\investigation\synthetic-scenario.json
```
完全なオフライン調査の流れは、依存関係（例: `pip install -e .[investigation]`）をインストールし、`spec.json` と `runtime.json` を用意して次を実行します。

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
rh monitor --workspace .local/d19-workspace run-once MONITOR_ID --scenario .\examples\investigation\synthetic-scenario.json
rh monitor --workspace .local/d19-workspace review --monitor-id MONITOR_ID
rh monitor --workspace .local/d19-workspace decide ISSUE_ID --decision relevant --note note
```
## 監視フィールドと deterministic replay

`profile.json` には `company_id`、`rule_version`、`scope` を、monitor spec には `name`、`report_languages` を必ず指定します。synthetic 周期の scenario には `cycle_key`、`window_start`、`window_end` を明示し、host はシステム時刻から期間を推定しません。profile 更新は次のように行います。

```powershell
./scripts/investigation.ps1 -Monitor -Command profile-update -Workspace .local/d19-workspace -RunId MONITOR_ID -Profile profile-v2.json
```

この adapter はアプリケーションサービスを呼ぶだけで、OS 監視やスケジューラをインストールせず、実際の API に接続しません。`scripts/investigation_replay.py` は `get_pending_tasks` の JSON を読み、`synthetic=true` と明記した zh/en/ja の決定的な構造化結果を生成します。これはテスト用 replay であり、実際のモデル推論や科学的効果を示しません。

```powershell
python scripts/investigation_replay.py --pending pending.json --output replay-result.json
```

軽量 host 依存関係は `pip install -e .[investigation]` でインストールします。

