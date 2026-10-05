# 研究エンジンと各地域の特許情報源

今回はオフライン候補として実装を進めます。[段階別状態](INTEGRATION_STAGE.md) と [有効化条件](INTEGRATION_ACTIVATION.md) を参照してください。インストール、コンポーネント試験、実際の調査の受入結果は別々に記録します。

開始前に問い、資料範囲、情報源の権限、モデル設定と数値予算を確定し、文書版と解析リビジョンを固定します。再解析は新しいリビジョンを作り、過去の報告は元の版を参照します。公開資料、合成例と社内資料を区別してください。

PaperQA2／STORM は草稿と候補主張を生成します。引用は内部の文書、版、解析リビジョンと原文位置に一意に対応する必要があります。不明・不一致の場合は確認待ちとなります。引用文の一致だけでは意味的な支持を証明できず、解釈や言い換えも個別に受け入れる必要があります。

デスクトップ EXE と追加の研究環境は分離します。`packaging/install_research_env.ps1` に基礎 Python、コア wheel、コア lock とエンジン lock の絶対パスを渡します。lock が競合する場合、環境を作る前に停止します。インストール記録には wheel と lock のハッシュが残ります。

生成設定の `research_engine.python_executable` を完全な実行設定に反映し、選択したエンジンに必要なモデル、埋め込みとキャッシュ設定を補ってください。インストール記録は完全な実行設定ではありません。実行時には依存パッケージを追加せず、不足条件は診断で確認します。

PowerShell 7.0 以降を使ってください。Windows PowerShell 5.1 はインストール・ビルドスクリプトの対象外です。配布パッケージのルートから次の PowerShell 例を使います。基礎 Python のパスを、インストール済みのローカル CPython 3.12 に置き換え、環境とインストール記録の保存先を指定してください。インストールでは固定された公開依存を取得しますが、調査は開始しません。

```powershell
$basePython = 'C:\replace\Python312\python.exe'
$bundle = (Get-Location).Path
$runtime = Join-Path $bundle 'optional-runtime'
& (Join-Path $runtime 'install_research_env.ps1') -Profile paperqa -BasePython $basePython -CoreWheel (Join-Path $runtime 'wheels\research_harness-0.1.0-py3-none-any.whl') -CoreLockFile (Join-Path $runtime 'requirements\core-lock.txt') -LockFile (Join-Path $runtime 'requirements\paperqa-runtime.txt') -EnvironmentPath (Join-Path $bundle 'research-envs\paperqa') -ConfigPath (Join-Path $bundle 'research-envs\paperqa.installation.json')
```

STORM は別の環境・設定パスと専用 lock を使います。PaperQA の環境には追加しません。

認証情報は指定した環境変数で設定し、資料、実行 JSON、報告やリポジトリには保存しません。実調査には新しい実行と明示的な数値予算が必要です。モデル、埋め込みと情報源への物理リクエストは同じ予算を使います。結果不明の呼び出しは予約を保持し、自動で再送しません。

番号照会、キーワード検索、案件補足、ファイル取得と用語照会は別々の能力です。情報源を有効にしても全操作が使えるとは限りません。[情報源一覧](SOURCE_API_MATRIX.md) を確認してください。認証不足、仕様不足、失敗と正常な空結果を区別します。

原文位置と連続引用を確認した後、比較可能な条件で主張を支持するか判断します。不合格ブロックには草稿と診断が残ります。出力後に終了・再起動して、過去の報告、確認履歴、呼び出し記録と予算を確認してください。再生は保存入力を使い、再検索しません。

Windows は軽量 EXE と追加研究環境を使います。サービスは `python -m research_harness.gui` で起動し、既定では `127.0.0.1` に接続待ちします。他のアドレスには `--host` と厳密な `--allowed-hosts` が必要です。初版の自前運用は単一利用者または信頼できるネットワーク向けです。

Docker はコア、追加研究と独立 Demo の構成を用意し、作業領域と資料庫を永続ボリュームに置きます。再構築と復旧は実際の Docker ホストで試験してください。公開 Demo は合成例または再配布許可のある固定資料だけを使い、サーバー側で実モデル、取得、アップロードと管理書き込みを拒否します。今回は配備設定を渡し、インターネット公開は行いません。

科学的比較は [評価手順](INTEGRATION_EVALUATION.md) に従います。未判定の主張は未評価のまま残し、費用や品質の改善を推測しません。

特許構造の入口は `rh patent-analyze --input "C:\path\to\AEM\examples\patent_analysis\frozen-input.synthetic.json"` です。実際の絶対ローカルパスに置き換えてください。例は合成資料です。アルゴリズムの固定依存は `requirements/patent-analysis-lock.txt` にあり、不足時は部分結果と診断を返し、終了コードは 4 です。分析は主張を受け入れず、調査データベースを書き換えません。

コアパッケージをインストールした環境で、完全なソースのルートからオフライン評価例を実行します。

```sh
python scripts/evaluate_integration.py --case examples/integration_evaluation/case.json --results-dir examples/integration_evaluation --annotations examples/integration_evaluation/annotations-template.json --output evaluation-offline.json
```

これは手順と有効化待ちの状態を確認する例で、三つの方式による実調査の比較ではありません。実際の判定は別ファイルに保存し、`--annotations` を置き換えてください。固定例は上書きしません。

## 情報源の実行

情報源の診断は `rh patent-source-diagnose --workspace "C:\path\to\investigation" --run-id RUN_ID` を使います。明示的な実行は現在 CLI から行います。GUI／HTTP API には情報源の実行操作をまだ追加していません。作業領域は `investigation.sqlite` を含む調査ディレクトリです。

```powershell
rh patent-source-execute --workspace "C:\path\to\investigation" --run-id RUN_ID --task-id TASK_ID --task-version 1 --request-id NEW_REQUEST_ID --source jpo --operation app_progress --params-file "C:\path\to\jpo-params.json" --input-refs-file "C:\path\to\frozen-task-refs.json"
```

ID とタスクの版を置き換えてください。現在のタスクは `GET /api/v1/runs/{run_id}/tasks` または `InvestigationService.get_pending_tasks` で読み、実際の `input_refs` 配列を参照ファイルに保存します。パラメータはローカル UTF-8 JSON オブジェクトです。JPO `app_progress` は有効な `application_number` が必要です。認証情報は設定済みの環境変数だけで渡します。新規実行の情報源予算は既定で 0 です。応答原本は解析待ちの草稿で、受け入れ済み証拠にはなりません。終了コードは完了／該当なしが 0、有効化待ち／部分結果が 4、不正な入力が 2 です。結果不明の要求を別の要求 ID で自動再送しないでください。

## Docker

Docker には完全なソースルートをビルドコンテキストとして渡し、利用可能な Docker ホストを使います。

```sh
docker compose --env-file compose.env.example up --build research
docker compose --env-file compose.env.example --profile demo up --build demo
docker compose --env-file compose.env.example --profile paperqa up --build research_paperqa
docker compose --env-file compose.env.example --profile storm up --build research_storm
```

既定のポート公開先はローカルホストです。ホスト名は `RH_ALLOWED_HOSTS` に明示します。作業領域と資料庫のボリュームを保持し、再構築では `down -v` を使いません。Dockerfile や Compose ファイルだけでは完全なビルドコンテキストになりません。このホストではイメージの構築・実行は未実施です。
