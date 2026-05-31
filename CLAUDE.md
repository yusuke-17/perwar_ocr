# プロジェクトルール

## 概要
戦前の日本語公文書（JACAR資料等）をOCRで読み取り、現代日本語に変換するツール。
完全ローカル実行（資料の外部送信禁止）。

## 技術スタック
- Python 3.13+ / uv（パッケージ管理）
- Ollama + GLM-OCR（メインOCRエンジン、0.9B）
- Surya OCR（補助・比較用）
- 後処理: senzen_word（旧字体・仮名変換、自作PyPIパッケージ）、jaconv（全角正規化）、LLMリライト（qwen3.5:9b）

## よく使うコマンド
すべての機能は統合CLI `prewar`（`scripts/cli.py`）に集約。引数なしで対話メニュー、
サブコマンドで直接実行も可。旧 `prewar-ocr` / `prewar-library` は後方互換で残存。

```bash
# 対話メニュー（OCR / 撮りため / 検索 / 口語体変換 / 環境確認）
uv run prewar

# 画像 → OCR → 正規化 → 口語体変換（一括実行）
uv run prewar ocr input/画像.png

# ライブラリ全文検索 / インデックス更新 / 統計
uv run prewar search 関東大震災
uv run prewar index
uv run prewar stat

# テキスト後処理（正規化/口語体化）
uv run prewar fix output/x.txt

# 環境確認
uv run prewar check

# 依存パッケージ同期・追加
uv sync
uv add <package>
```

## ディレクトリ構成
- `pkg/senzen_word/` - 自作文字変換ライブラリ（PyPI公開用、独立パッケージ）
- `scripts/` - 実行スクリプト（CLI）
- `utils/` - PJ固有ユーティリティ（Ollama, OCR, LLM等）
- `input/` / `output/` - 入出力データ（Git管理外）
- `plan/` - 実装計画
- `survey/` - 調査レポート

## 開発ルール
- Python実行は必ず `uv run` 経由
- 機密資料（input/, output/）はGit管理しない
- 新しいライブラリ追加時は `uv add` を使用
- **外部API・クラウドサービスへの資料送信は絶対禁止**

## 重要な制約
- 対象文書: 旧字体、カタカナ仮名遣い、歴史的仮名遣い、右横書き
- NVIDIA GPUなし → NDLOCR ver.2は使用不可
- 外部送信禁止 → クラウドOCR APIは使用不可

## コード規約
- 既存パターンに従う: argparse CLI、dataclass、カスタム例外クラス
- 日本語コメント・docstring
- ファイルパスは `pathlib.Path` を使用
- スクリプトは `scripts/`、PJ固有モジュールは `utils/`、文字変換は `pkg/senzen_word/` に配置
- senzen_word は外部依存ゼロ（Ollama, jaconv等に依存させない）
