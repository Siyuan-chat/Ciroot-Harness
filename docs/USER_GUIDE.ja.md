# 日本語ユーザーガイド（実装済み Alpha）

実装済み Alpha の CLI を説明します。`python -m pip install --no-build-isolation -e .` でインストールしてから `rh --help` を実行します。初版はローカルで動作し、ユーザーの指示で更新します。ポリマー設計の事例は未検証です。

## 1. 作業領域と API

調査目的は research.json、サービスやモデルの選択は runtime.json に保存します。認証情報は環境変数で渡し、設定には変数名だけを記載します。

[実行設定テンプレート](../examples/runtime.example.json) のモデルは null で、未選択を示します。このままでは実行できません。Terra が実接続を検証したローカル多言語 Embedding の既定値を用意し、ユーザーは利用可能な生成モデルを設定します。Schema が正しくても API やモデルが利用できるとは限りません。

OpenAlex と EPO の認証・本文収録範囲は別です。書誌情報が見つかっても全文を取得できるとは限りません。対応済みサービスは設定で変更でき、新しい API にはアダプターが必要です。

原文、データベース、索引、対話履歴、レポートは workspace/ に保存し、既定では Git に含めません。Embedding はローカルで生成し、分析に必要な原文の抜粋は設定したモデルに送信できます。外部の音声文字起こしを chat に貼り付けられます。初版に録音機能はありません。

## 2. 設定確認と調査目的の入力

以下は実装予定のコマンドです。

```text
rh doctor --runtime runtime.json --workspace workspace
rh chat --runtime runtime.json --workspace workspace --lang ja
```

doctor は既定でローカル検査のみを行い、認証情報、依存関係、モデル選択の不足を説明します。明示的なオンライン検査はローカル検査と区別します。

例えば「選定したポリマーの設計について、手元の論文と特許を参照して、設計方針と性能に関する証拠を比較したい」と伝えます。

LLM は結果に影響する点を一つずつ確認し、既知の回答を利用して、要約とバージョン付き JSON を作成します。科学的な閾値を勝手に補いません。要件変更は新しい版として保存し、「調査を開始」「調査を更新」などの明確な指示で実行します。

[ポリマー設計の草案](../examples/polymer-design.draft.json) は方向性だけを記録したもので、完全な事例入力ではありません。自動実行されません。

## 3. 参照資料の取り込み

```text
rh import ./my-paper.pdf --workspace workspace --collection baseline --kind paper
rh import ./my-patent.xml --workspace workspace --collection baseline --kind patent
```

原文のバージョンと位置を保持します。新たに検索した資料は発見ライブラリに入り、参照ライブラリへの追加は明示的に行います。調査開始時に比較基準の版を固定します。

## 4. 更新・再開・レポート

chat で更新、進捗確認、注目点の変更を自然言語で指示できます。同じ機能を明示的なコマンドでも呼び出せます。

```text
rh validate --spec research.json
rh run --spec research.json --runtime runtime.json --workspace workspace
rh status --workspace workspace
rh resume RUN_ID --runtime runtime.json --workspace workspace
rh report RUN_ID --workspace workspace --languages zh,en,ja
```

候補数、検索回数、モデル呼び出し、ダウンロード量、実行時間に上限を設けます。上限に達したら取得済み結果を保存し、部分レポートを生成します。モデル料金の見積もりは実際の請求額ではなく、料金情報がない場合はゼロではなく不明と表示します。

HTML/Markdown レポート、正規化 JSON、確認リストの CSV を出力します。三言語で事実と ID を共有し、検索完了で追加なしの場合と、データソースに接続できなかった場合を区別します。技術マップと注目項目から原文の証拠を参照できます。

## 5. 人による判断

```text
rh review list --workspace workspace --lang ja
rh review decide ISSUE_ID --decision watch --note "追加証拠を待ちながら注視" --workspace workspace
```

判断は include（採用）、exclude（除外）、watch（継続注視）、request_more_evidence（追加調査依頼）です。人が watch を選んだ項目は判断済みで、未回答の証拠不足項目とは区別します。追加調査は次回のユーザー指示による実行時に行います。

同じ問題を重複登録しません。新しい重要な証拠が得られた場合は過去の判断を残して再確認対象にします。三言語の状態は共通です。個別判断によって全体の判定基準は変わりません。全体を変更する場合は明示的に指示します。

## 6. 結果の読み方

- 未報告の値はゼロや不合格を意味しません。
- 測定条件が異なる値を直接比較しません。
- 要約、請求項、明細書、実施例、論文の実験結果を区別します。
- 引用位置が正しくても結論の正しさが保証されるわけではなく、重要な判断は確認可能です。
- 過去のレポートは当時の状態を保持します。新しい確認結果で履歴を消しません。
- 現在は設計資料のみです。実装後はローカルテスト、実 API 検証、科学事例の受入結果を区別して示します。
