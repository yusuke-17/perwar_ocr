# 戦前日本語OCR

戦前の日本語公文書（JACAR資料等）をOCRで読み取り、現代日本語に変換するツール。

Ollama + GLM-OCR（OCR専用Vision LLM）をMacのローカルで動かすことで、CJK文字の高精度認識を **データ漏洩ゼロ** で実現する。

## 前提条件

- Apple Silicon Mac（M1〜M4）
- RAM 16GB 以上推奨（8GBでも動作可能）
- Python 3.13 以上
- [Ollama](https://ollama.com/download/mac) がインストール済みであること
- [uv](https://docs.astral.sh/uv/) がインストール済みであること

## セットアップ

### 1. Ollama のインストール

https://ollama.com/download/mac からダウンロードし、Applications にドラッグして起動する。

### 2. モデルのダウンロード

```bash
# OCR用モデル（必須）
ollama pull glm-ocr

# 口語体変換用モデル（必須）
ollama pull qwen3.5:9b
```

### 3. uv のインストールと依存パッケージの導入

```bash
# uv のインストール（未導入の場合）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 依存パッケージのインストール
cd ~/Desktop/prewar-ocr
uv sync
```

### 4. セットアップ確認

```bash
uv run python scripts/setup_check.py
```

## 使い方

```bash
# 対話モード（input/ の画像を一覧から選択して実行）
uv run prewar-ocr

# 画像を直接指定して実行
uv run prewar-ocr input/画像.png
```

実行すると `library/{YYYY-MM-DD}_{画像名}/` フォルダが作られ、1回の処理結果が「1件の記録」として保存される。

### 出力フォーマット

```
library/
└── 2026-05-24_画像名/
    ├── source.png       元画像のコピー（複数枚なら source_01.png, source_02.png ...）
    ├── ocr_raw.txt      OCR生テキスト（正規化前）
    ├── modern.txt       現代語テキスト（最終成果物）
    └── meta.json        処理メタ情報（モデル・設定・処理時間）
```

`meta.json` には使用モデル・正規化設定・処理時間などが記録され、後から検索・再実行・修正の素材として使える。

### オプション

```bash
# 旧形式（output/{画像名}_modern.txt）も併せて出力
uv run prewar-ocr input/画像.png --legacy-output

# ライブラリのルートディレクトリを変更
uv run prewar-ocr input/画像.png --library-root mylib/

# ファイル保存せずコンソール出力のみ
uv run prewar-ocr input/画像.png --no-save

# OCR用モデルを変更
uv run prewar-ocr input/画像.png -m qwen3-vl
```

## フォルダ構成

| フォルダ | 用途 |
|----------|------|
| `input/` | OCR対象の画像ファイルを置く |
| `library/` | 処理結果の蓄積先（1文書＝1フォルダ） |
| `output/` | `--legacy-output` 指定時の旧形式出力先 |
| `scripts/` | OCR実行スクリプト |
| `utils/` | OCR・正規化・口語体変換・ライブラリ保存などのユーティリティ |
| `pkg/senzen_word/` | 旧字体・仮名変換ライブラリ（自作PyPIパッケージ） |
| `plan/` | 実装計画 |
| `survey/` | 調査レポート |
