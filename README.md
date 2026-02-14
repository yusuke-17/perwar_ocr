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

### 2. GLM-OCR モデルのダウンロード

```bash
ollama pull glm-ocr
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

### OCR実行（画像 → テキスト）

```bash
# 基本的な使い方（結果は output/ に保存される）
uv run python scripts/ocr_vision_llm.py input/画像.png

# 出力先を指定
uv run python scripts/ocr_vision_llm.py input/画像.png -o results/

# ファイル保存せずコンソール出力のみ
uv run python scripts/ocr_vision_llm.py input/画像.png --no-save

# 別のモデルを使う場合
uv run python scripts/ocr_vision_llm.py input/画像.png -m qwen3-vl
```

### 旧字体→現代語変換（テキスト後処理）

```bash
# 単一ファイルの変換（→ 元ファイル名_modern.txt が生成される）
uv run python scripts/postprocess.py output/sample_ocr.txt

# 出力先を指定
uv run python scripts/postprocess.py output/sample_ocr.txt -o output/sample_modern.txt

# フォルダ内の全 .txt を一括変換
uv run python scripts/postprocess.py output/ -o output_modern/

# 変換箇所の詳細を表示
uv run python scripts/postprocess.py output/sample_ocr.txt --diff

# 旧字体変換のみ（仮名遣い変換をスキップ）
uv run python scripts/postprocess.py output/sample_ocr.txt --no-kana
```

### 典型的なワークフロー

```bash
# 1. 画像をOCRで読み取る
uv run python scripts/ocr_vision_llm.py input/戦前文書.png

# 2. 旧字体・旧仮名を現代語に変換する
uv run python scripts/postprocess.py output/戦前文書_ocr.txt

# → output/戦前文書_ocr_modern.txt が生成される
```

## フォルダ構成

| フォルダ | 用途 |
|----------|------|
| `input/` | OCR対象の画像ファイルを置く |
| `output/` | OCR結果のテキストが出力される |
| `scripts/` | OCR実行・後処理などのスクリプト |
| `utils/` | 旧字体辞書・仮名変換などのユーティリティ |
| `plan/` | 実装計画 |
| `training_data/` | 精度検証用の正解データ（画像・ラベル） |
| `survey/` | 調査レポート |
