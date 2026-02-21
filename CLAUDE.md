# プロジェクトルール

## 概要
戦前の日本語公文書（JACAR資料等）をOCRで読み取り、現代日本語に変換するツール。
完全ローカル実行（資料の外部送信禁止）。

## 技術スタック
- Python 3.13+ / uv（パッケージ管理）
- Ollama + GLM-OCR（メインOCRエンジン、0.9B）
- Surya OCR（補助・比較用）
- 後処理: 旧字体変換（辞書ベース）、仮名変換、LLMリライト（qwen3:14b）

## よく使うコマンド
```bash
# OCR実行
uv run python scripts/ocr_vision_llm.py input/画像.png

# 後処理（旧字体・仮名変換）
uv run python scripts/postprocess.py output/結果.txt

# 後処理（文語体→口語体リライト含む）
uv run python scripts/postprocess.py output/結果.txt --modernize

# 環境確認
uv run python scripts/setup_check.py

# 依存パッケージ同期・追加
uv sync
uv add <package>
```

## ディレクトリ構成
- `scripts/` - 実行スクリプト（CLI）
- `utils/` - ユーティリティモジュール（ライブラリ）
- `input/` / `output/` - 入出力データ（Git管理外）
- `models/` - モデルファイル（Git管理外）
- `training_data/` - 精度検証用データ（images/はGit管理外）
- `plan/` - 実装計画
- `survey/` - 調査レポート

## 開発ルール
- Python実行は必ず `uv run` 経由
- 機密資料（input/, output/, training_data/images/）はGit管理しない
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
- スクリプトは `scripts/`、モジュールは `utils/` に配置
