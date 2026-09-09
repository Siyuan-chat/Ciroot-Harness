# Research Harness

[中文](README.zh-CN.md) · [English](README.md) · 日本語

ローカルの文献・特許調査フレームワークです。目標の流れは、自然言語の要件 → バージョン付き JSON → 検索 → 固定した参照資料との比較 → 人による確認とレポートです。

**現在は D2 合成フィクスチャ段階で、最終受入は未完了です。** デモは合成テキストとローカルの情報源／モデル関数を使い、実際の LangGraph、SQLite、引用検証と中国語・英語・日本語レポートを動作させます。API キーや外部 API は使いません。

## クイックスタート

Python 3.11+ が必要です。Windows のソースディレクトリで実行します。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install .
.venv\Scripts\rh demo --workspace .local\demo
.venv\Scripts\rh status --workspace .local\demo
```

インストール時は宣言済みの依存パッケージを取得します。デモ自体はオフラインです。macOS/Linux では `.venv/bin/python` と `.venv/bin/rh` を使用します。独立実行検証は現在 Windows が対象です。

デモは合成候補2件、検証後の判定、確認事項1件、HTML 3ファイル、Markdown 3ファイル、共通 JSON、確認用 CSV を生成します。返されたレポートディレクトリから HTML を開けます。

## 現在の機能

- ResearchSpec 検証、手動編集後の自動改訂、実行入力の固定。
- ローカル原文とエビデンス、参照スナップショットと新規候補の分離。
- 差し替え可能な fixture 情報源／モデル関数と最小 LangGraph フロー。
- 引用の所属／原文一致、人の判断の保存、候補数上限、一部完了／失敗の明示。
- 将来の GUI 用 Python サービス、構造化結果、安全なエラー、成果物参照、進捗コールバック。

実際のモデル／情報源 API、OpenAlex/EPO、実運用ベクトル RAG、PDF/OCR、独立 chat、再開処理、GUI は **D2 に未接続**です。追加依存パッケージだけでは有効になりません。未対応の live/chat は拒否し、`lexical_test_only` はテスト互換用です。現在はホストのアシスタントが要件を確認して JSON を用意します。

[日本語ガイド](docs/USER_GUIDE.ja.md) · [現在の範囲](docs/SCOPE_AUDIT.md) · [契約／アダプター](docs/CONTRACTS.md) · [受入 K01–K07](docs/ACCEPTANCE.md) · [要件](docs/PRD.md) · [構成](docs/ARCHITECTURE.md) · [決定事項](docs/DECISIONS.md)

最初の実例はポリマー設計を予定しています。[草案](examples/polymer-design.draft.json) には未確定要件があり、実行可能な科学的事例ではありません。実際の API 接続と事例／デモ検証後に GitHub で公開します。科学的事例や公開リリースの受入はまだ行っていません。

キー、非公開原文、実行ワークスペースは Git に保存しないでください。同梱デモは合成資料のみです。調査は手動で開始し、標準の定期実行はありません。
