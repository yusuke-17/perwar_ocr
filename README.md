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
# 画像 → OCR → 正規化 → 口語体変換（すべて自動実行）
uv run python scripts/ocr_vision_llm.py input/画像.png

# → output/画像_modern.txt が生成される
```

出力先やモデルの変更も可能:

```bash
# 出力先を指定
uv run python scripts/ocr_vision_llm.py input/画像.png -o results/

# ファイル保存せずコンソール出力のみ
uv run python scripts/ocr_vision_llm.py input/画像.png --no-save

# OCR用モデルを変更
uv run python scripts/ocr_vision_llm.py input/画像.png -m qwen3-vl
```

## フォルダ構成

| フォルダ | 用途 |
|----------|------|
| `input/` | OCR対象の画像ファイルを置く |
| `output/` | OCR結果のテキストが出力される |
| `scripts/` | OCR実行・後処理などのスクリプト |
| `utils/` | 旧字体辞書・仮名変換などのユーティリティ |
| `plan/` | 実装計画 |
| `survey/` | 調査レポート |
