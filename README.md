# 戦前日本語OCR

戦前の日本語公文書（JACAR資料等）をOCRで読み取り、現代日本語に変換するツール。

Ollama + Vision LLM（Gemma 3）をMacのローカルで動かすことで、クラウドAIと同等の画像認識を **データ漏洩ゼロ** で実現する。

## 前提条件

- M1/M2/M3 Mac（Apple Silicon）
- RAM 16GB 以上推奨（8GBでも動作可能）
- Python 3.10 以上
- [Ollama](https://ollama.com/download/mac) がインストール済みであること

## セットアップ

### 1. Ollama のインストール

https://ollama.com/download/mac からダウンロードし、Applications にドラッグして起動する。

### 2. Vision LLM モデルのダウンロード

```bash
# RAM 16GB以上の場合（推奨）
ollama pull gemma3:12b

# RAM 8GBの場合
ollama pull gemma3:4b
```

動作確認:

```bash
ollama run gemma3:12b "こんにちは、日本語で答えてください"
```

### 3. Python 環境の構築

```bash
cd ~/Desktop/prewar-ocr
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. セットアップ確認

```bash
python scripts/setup_check.py
```

## 使い方

```bash
source .venv/bin/activate

# 1枚の画像をVision LLMで処理
python scripts/pipeline.py input/sample.jpg -e vision_llm -m gemma3:12b

# 右横書きの画像
python scripts/pipeline.py input/rtl_document.jpg --rtl

# フォルダ一括処理
python scripts/pipeline.py input/ -o output/

# Surya OCRで処理（比較用）
python scripts/pipeline.py input/sample.jpg -e surya
```

結果は `output/` フォルダに出力される。

## フォルダ構成

| フォルダ | 用途 |
|----------|------|
| `input/` | OCR対象の画像ファイルを置く |
| `output/` | OCR結果のテキストが出力される |
| `models/` | 学習済みモデルの保存先 |
| `scripts/` | OCRパイプラインなどのスクリプト |
| `utils/` | ユーティリティ関数 |
| `training_data/` | 精度検証用の正解データ（画像・ラベル） |
| `survey/` | 調査レポート |
