# 利用ガイド：D2 fixture フレームワーク

D2 はオフライン処理と拡張インターフェースを検証する段階です。実際の API、実運用 RAG、PDF/OCR、独立 chat、GUI は未接続で、追加依存パッケージだけでは有効になりません。現在はホストのアシスタントが要件を確認し、ResearchSpec JSON を用意します。調査は手動で開始します。

## インストールと実行

Python 3.11+ が必要です。Windows のソースディレクトリで実行します。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .
.venv\Scripts\rh demo --workspace .local\demo
.venv\Scripts\rh status --workspace .local\demo
```

依存パッケージの取得にはネットワークまたは準備済みキャッシュが必要ですが、デモにはネットワークもキーも不要です。ビルド済み wheel は `.venv\Scripts\python -m pip install path\research_harness-0.1.0-py3-none-any.whl` で導入できます。実資料とは別のデモ用ディレクトリを使います。macOS/Linux の実行ファイルは `.venv/bin/` 配下です。独立実行検証は現在 Windows が対象です。

同梱 ready 設定はプロジェクト `fixture-demo`、合成候補2件、合成参照1件です。戻り値は `run_id/outcome/stage/error/artifacts.report` を含みます。出力先には3言語の HTML、3言語の Markdown、`report.json`、`review.csv` があり、標準では確認事項が1件作成されます。

## 合成入力の変更

次を `prepare_fixture.py` として保存・実行すると、インストール済みの例をコピーできます。

```python
from importlib.resources import files
from pathlib import Path
base = files('research_harness').joinpath('fixtures')
for source, target in [('demo-spec.json', 'research.json'), ('demo.json', 'candidates.json')]:
    Path(target).write_text(base.joinpath(source).read_text(encoding='utf-8'), encoding='utf-8')
```

topic、objectives、予算などを変更して実行します。

```powershell
.venv\Scripts\rh validate --spec research.json
.venv\Scripts\rh demo --workspace .local\custom --spec research.json --fixture candidates.json
```

validate は検証のみで、調査を開始しません。実行には `status=ready` と `unresolved_questions=[]` が必要です。同じ project/revision の内容を編集すると新しい改訂を保存し、同じ内容の再保存では既存版を再利用します。入力ファイルは上書きせず、過去の設定・参照・レポートを固定します。

fixture の形式は `{"candidates":[{"id":"synthetic-1","quote":"Synthetic text.","locator":"line:1"}]}` です。ID は一意、quote は空でない文字列です。任意の `missing:true` は根拠不足を演示します。検索結果や科学的主張ではありません。`--spec` 指定時は標準の参照資料を自動追加しません。単純なローカル `.txt` を選ぶ場合：

```powershell
.venv\Scripts\rh import baseline.txt --workspace .local\custom --collection baseline --kind paper
```

`reference_library.collection_ids/document_ids` で参照を選択します。新規候補は自動で基準になりません。ポリマー設計の例は後続の事例準備用 draft のままです。

## 人による確認と再出力

実行結果の ID を `RUN_ID` と `ISSUE_ID` に入れます。

```powershell
.venv\Scripts\rh review list --workspace .local\demo
.venv\Scripts\rh review decide ISSUE_ID --decision watch --note "追加根拠を待って再確認" --workspace .local\demo
.venv\Scripts\rh report RUN_ID --workspace .local\demo --languages zh,en,ja
```

include/exclude/watch は個別判断を保存して対応済みにします。request_more_evidence は未対応のまま残します。全体基準や過去のレポートは変更しません。過去の実行を再出力しても固定済みの事実を使い、現在の判断は review list で確認します。

## Python と将来の GUI

```python
from research_harness.service import Harness
from research_harness.errors import HarnessError
h = Harness('.local/custom')
try:
    result = h.run_fixture('research.json', 'candidates.json', on_progress=lambda e: print(e))
    print(h.status())
    print(h.get_result(result['run_id']))
    print(h.get_artifacts(result['run_id']))
except HarnessError as exc:
    print(exc.to_dict())
finally:
    h.close()
```

サービス自身は標準出力に書きません。進捗イベントは run_id/stage/status を含みます。get_result は解析済みの固定データ、get_artifacts は `{report,files}` と各ファイルの language/format/path、review_decide は更新した確認事項を返します。SQLite や CLI 出力の解析は不要です。

`source_adapter(candidates)` と `model_adapter(spec,candidate,candidate_evidence,reference_evidence)` を差し替えられます。モデル出力は disposition/comparison_result/rationale と双方の引用 `{evidence_id,quote}` を持つ通常の JSON データです。所属と原文一致をフレームワークが検証します。[契約](CONTRACTS.md) を参照してください。実サービスには対応アダプターの実装が別途必要です。

## 結果と範囲

demo の終了コードは completed=0、partial=4、failed=3、不正入力=2 です。max_candidates 超過時は部分結果を保存し、情報源や出力の失敗も明示します。RH_INVALID_INPUT、RH_PRECONDITION、RH_NOT_FOUND、RH_EXPORT_FAILED、RH_UNSUPPORTED は安定したエラーコードです。公開エラーに外部例外の生テキストは含めません。

代表的な予算／失敗経路を対象とし、クラッシュ復旧や全予算項目は保証しません。chat/live は未対応、lexical_test_only は旧テスト互換用です。原文、キー、SQLite、レポートは Git 対象外のワークスペースに保存します。実 API／資料庫の接続、ポリマー事例の受入、GitHub 公開は後続段階です。
