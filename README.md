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
uv run prewar check
```

## 使い方

すべての機能は `prewar` コマンド1つに集約されている。**コマンドを覚えていなくても、引数なしで実行すれば対話メニューが出る**ので、矢印キーで選ぶだけでよい。

```bash
# 対話メニュー（OCR / 撮りため / 検索 / 口語体変換 / 環境確認 を矢印キーで選択）
uv run prewar
```

慣れたらサブコマンドで直接実行もできる（速い）。

| やりたいこと | コマンド |
|------------|---------|
| 画像をOCR→現代語化 | `uv run prewar ocr input/画像.png` |
| 範囲スクショで撮りため | `uv run prewar shoot` |
| ライブラリを全文検索 | `uv run prewar search 関東大震災` |
| 検索インデックス更新 | `uv run prewar index` |
| ライブラリ統計 | `uv run prewar stat` |
| テキスト後処理（正規化/口語体化） | `uv run prewar fix output/x.txt` |
| 環境確認 | `uv run prewar check` |

```bash
# OCR: 対話モード（input/ の画像を一覧から選択して実行）
uv run prewar ocr

# OCR: 画像を直接指定して実行
uv run prewar ocr input/画像.png
```

> 旧コマンド `uv run prewar-ocr` / `uv run prewar-library` も後方互換でそのまま使える。

実行すると `library/{YYYY-MM-DD}_{画像名}/` フォルダが作られ、1回の処理結果が「1件の記録」として保存される。

### 範囲スクショで撮りため → 一括処理（macOS）

ブラウザ上の資料を範囲スクショで取り込む場合は `shoot` を使う。macOS標準の範囲選択（`screencapture -i`）で本文だけをドラッグして囲うため、ブラウザのUIや周辺本文がOCR対象に写り込まない。複数ページを撮りためてから最後にまとめて処理できる。

```bash
# 範囲スクショを繰り返し撮影 → 終了時にそのまま一括処理
uv run prewar shoot

# 撮るだけ（処理は後回し）
uv run prewar shoot --no-run

# 貯めたセッションフォルダを後からまとめて処理（1記録として保存）
uv run prewar ocr input/session_2026-05-31_103000/

# フォルダ内を画像ごとの別記録として処理
uv run prewar ocr input/session_2026-05-31_103000/ --separate
```

- 撮った画像は一時置き場 `input/session_{日時}/p001.png, p002.png ...` に撮った順（＝ページ順）で貯まる。
- 既定では1セッションを結合して「1件の長い文書」として保存する（同一資料の複数ページ撮影向け）。`--separate` で画像ごとの別記録に切り替えられる。
- セッションフォルダは処理後も残る（`library/` にコピー保存済み。撮り直し用に手元に残す。不要なら手動で削除）。
- `shoot` は macOS 専用。他OSでは画像を `input/` に置いてフォルダ/パス指定で処理する。

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
# 正規化（旧字体・仮名・誤読修正）をスキップ
uv run prewar ocr input/画像.png --no-normalize

# 口語体変換（LLMリライト）をスキップ
uv run prewar ocr input/画像.png --no-modernize

# 旧形式（output/{画像名}_modern.txt）も併せて出力
uv run prewar ocr input/画像.png --legacy-output

# ライブラリのルートディレクトリを変更
uv run prewar ocr input/画像.png --library-root mylib/

# ファイル保存せずコンソール出力のみ
uv run prewar ocr input/画像.png --no-save

# OCR用モデルを変更
uv run prewar ocr input/画像.png -m qwen3-vl

# 撮影のみ行い処理は後回し（shoot と併用）
uv run prewar shoot --no-run

# フォルダ内を画像ごとの別記録として処理
uv run prewar ocr input/session_.../ --separate
```

## ライブラリ検索

`library/` に溜まった文書を全文検索する。SQLite FTS5 + trigram tokenizer を使うため日本語の部分一致が効き、追加パッケージは不要（Python標準ライブラリのみ）。

### 検索インデックスの構築

```bash
# 差分更新（meta.json の mtime を見て変更分だけ更新）
uv run prewar index

# 全件再構築（インデックス破損時など）
uv run prewar index --rebuild
```

### キーワード検索

```bash
# 単一語
uv run prewar search 関東大震災

# 複数語スペース区切り = AND（両方を含む文書のみヒット）
uv run prewar search 関東大震災 警察報告

# 表示件数を変更（デフォルト20件）
uv run prewar search 関東大震災 --limit 50

# JSON 出力（パイプ処理用）
uv run prewar search 関東大震災 --format json
```

検索対象は `modern.txt` と `meta.json` の `title` のみ。`ocr_raw.txt`（旧字体の生テキスト）はインデックス外。

> ⚠️ trigram の仕様上、検索語は **3文字以上**が必要（2文字以下は警告して中断）。

### ライブラリ統計

```bash
uv run prewar stat
```

文書数・インデックスサイズ・最終更新日が表示される。

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
