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
- `config.toml` - 設定の上書きファイル（モデル名/パス/チャンク/LLM/OCR/Ollama通信/検索）。Git管理
- `openspec/` - 仕様駆動開発（OpenSpec）。`specs/` が正の仕様、`changes/` が進行中の変更
- `plan/` - 改善案バックログ（個別変更の設計は書かない）
- `survey/` - 調査レポート

## 開発ルール
- Python実行は必ず `uv run` 経由
- 機密資料（input/, output/）はGit管理しない
- 新しいライブラリ追加時は `uv add` を使用
- 設定値はコードに直書きせず `config.toml` で管理（デフォルトの正解は `utils/config.py` の `_DEFAULTS`、`config.toml` は差分のみ）
- **外部API・クラウドサービスへの資料送信は絶対禁止**

## 仕様駆動開発（OpenSpec）
機能追加・仕様変更は OpenSpec のフローで進める。コードを書く前に仕様とタスクを合意する。

```
/opsx:explore          # 現状コードを読んで論点を整理（任意）
/opsx:propose <変更名>  # 仕様・設計・タスクを起草 → 人がレビューして承認
/opsx:apply            # 承認済みタスクに沿って実装
/opsx:archive          # 完了。差分仕様を openspec/specs/ に統合
```

- 生成物は日本語（構造見出しと SHALL/MUST は英語のまま）。設定は `openspec/config.yaml`
- 誤字修正や1行の変更まで OpenSpec に載せる必要はない。判断に迷う規模なら載せる

## ドキュメントの役割分担
書く場所を迷ったらこの表に従う。同じ内容を2箇所に書かない。

| 置き場 | 役割 |
|---|---|
| `openspec/changes/<名前>/` | **個別変更の提案・設計・タスク**。設計文書は必ずここ（`plan/` に新規作成しない） |
| `openspec/specs/` | 完了した変更が統合された「正」の仕様 |
| `plan/improvement-ideas.md` | やるかもしれない改善案のバックログ。着手時に OpenSpec の変更へ引き上げる |
| `survey/` | 調査レポート。仕様に変換せず、`/opsx:explore` の参照材料として使う |
| `PROGRESS.md` | 現在地と作業履歴の一枚絵。設計の詳細は書かずリンクする |
| `README.md` | 使い方・全体像（利用者向け） |
| `CLAUDE.md` | AI向けの恒久ルール（このファイル） |

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
