# 戦前日本語OCR — 実装プラン

作成日: 2026-02-10

---

## Context（なぜこの変更が必要か）

戦前日本語公文書をOCRで読み取りたいが、以下の制約がある:
- **M1 Mac** → NVIDIA GPUなし → NDLOCR使用不可
- **資料の外部送信禁止** → ChatGPT/Claude等のクラウドAI不可
- ChatGPT等のクラウドAI（Vision機能）は精度が高いが、外部送信になるので使えない

**解決策**: **Ollama + Vision LLM（Gemma 3等）をMacのローカルで動かす**ことで、クラウドAIと同等の画像認識をデータ漏洩ゼロで実現する。

---

## アーキテクチャ

```
入力画像 → [画像前処理(OpenCV)] → [OCR] → [後処理(必要時)] → 出力テキスト
                                      |
                         +-------------+-------------+
                         |                           |
                  [メイン] Vision LLM          [補助] Surya OCR
                  Gemma 3 via Ollama           従来型文字認識
                  (Macネイティブ)              (Macネイティブ)
```

### Vision LLMがメインの理由

- **従来OCR**（Surya等）= 学習した文字パターンを「認識」
  → 旧字体は学習データにないので弱い
- **Vision LLM**（Gemma 3等）= 画像全体を「理解」して文字を「推論」
  → 旧字体でも文脈から推測可能
- さらにプロンプト指示で「旧字体→新字体変換」まで一発で可能（後処理不要の可能性）

### 環境方針

| コンポーネント | 実行環境 | 理由 |
|---|---|---|
| Ollama + Vision LLM | **Macネイティブ** | Metal GPU加速が必須（Docker内だと激遅） |
| Pythonスクリプト | **Macネイティブ (uv)** | 高速な依存管理 + Ollamaとの連携がシンプル |
| Surya OCR | **Macネイティブ (uv)** | PyTorch Metal加速が活きる |

> **パッケージマネージャ**: `uv`（Rust製の高速Pythonパッケージマネージャ）を使用。
> `pip` + `venv` の代わりに `uv` が仮想環境の作成・依存管理・スクリプト実行をすべて行う。

---

## プロジェクト構成（改訂版）

```
prewar-ocr/
├── input/                     # 入力画像を置くフォルダ
├── output/                    # 出力テキストの保存先
├── models/                    # 学習済みモデル保存先
├── training_data/             # 精度検証用の正解データ
│   ├── images/                # テスト画像
│   └── labels/                # 正解テキスト（手動作成）
├── scripts/
│   ├── setup_check.py         # Step 1: 環境構築の動作確認
│   ├── preprocess.py          # Step 2: 画像前処理 (OpenCV)
│   ├── ocr_vision_llm.py      # Step 3: Vision LLM によるOCR (Ollama)
│   ├── ocr_surya.py           # Step 3: Surya OCR エンジン
│   ├── ocr_compare.py         # Step 3: 全エンジン比較テスト
│   ├── postprocess.py         # Step 4: 後処理パイプライン
│   └── pipeline.py            # Step 5: 全体統合パイプライン
├── utils/
│   ├── char_converter.py      # 旧字体→新字体 変換辞書
│   ├── kana_converter.py      # 歴史的仮名遣い→現代仮名遣い
│   └── ollama_client.py       # Ollama API ラッパー
├── survey/                    # 調査レポート
├── pyproject.toml             # プロジェクト設定 & 依存管理 (uv)
├── .gitignore
└── README.md
```

---

## 実装ステップ

### Step 1: 環境構築

**目的**: Ollama + Gemma 3 Vision をMacで動かせるようにする

#### 手順

1. **Ollamaインストール**
   - https://ollama.com/download/mac からダウンロード
   - Ollama.app を Applications にドラッグ
   - 起動（メニューバーにアイコンが出る）

2. **Vision LLMモデルをダウンロード**
   ```bash
   # RAM 16GB以上のMacの場合（推奨）
   ollama pull gemma3:12b

   # RAM 8GBのMacの場合
   ollama pull gemma3:4b

   # 比較用（オプション）
   ollama pull qwen3-vl:8b
   ```

3. **Ollama動作確認**
   ```bash
   ollama run gemma3:12b "こんにちは、日本語で答えてください"
   ```

4. **uvでプロジェクト初期化 & 依存パッケージ追加**
   ```bash
   cd ~/Desktop/prewar-ocr

   # プロジェクト初期化（pyproject.toml が作られる）
   uv init

   # Python 3.13 を使うように固定
   uv python pin 3.13

   # 依存パッケージを追加（自動で .venv も作られる）
   uv add ollama surya-ocr opencv-python-headless Pillow numpy
   ```

   > **解説**: `uv add` を実行すると、uv が自動的に以下をやってくれる:
   > 1. `.venv/` 仮想環境を作成（なければ）
   > 2. パッケージをインストール
   > 3. `pyproject.toml` に依存を記録
   > 4. `uv.lock` ロックファイルを生成（再現性のため）
   >
   > `pip install` や `source .venv/bin/activate` は不要！

5. **動作確認スクリプト実行**
   ```bash
   uv run python scripts/setup_check.py
   ```

   > **解説**: `uv run` は自動的に仮想環境をアクティベートしてからコマンドを実行する。
   > `source .venv/bin/activate` を手動で行う必要がない。

#### 作成・修正するファイル

| ファイル | 操作 | 内容 |
|---|---|---|
| `pyproject.toml` | 新規 | `uv init` + `uv add` で自動生成される |
| `uv.lock` | 新規 | `uv add` で自動生成（依存の再現性のため） |
| `scripts/setup_check.py` | 新規 | Ollama接続確認、Vision LLM動作確認、Surya確認 |
| `.gitignore` | 修正 | .venv/, .env, temp_*, __pycache__/ 等 |

---

### Step 2: 画像前処理

**目的**: OCRの精度を上げるための画像補正

#### 2つの前処理モード

| モード | 対象 | 処理内容 |
|---|---|---|
| Vision LLM用 | Gemma 3等 | 軽い補正のみ（コントラスト調整、右横書き反転）。二値化しない |
| 従来型OCR用 | Surya OCR | フル前処理（グレースケール、ノイズ除去、適応的二値化） |

**なぜ分けるのか**: Vision LLMは元画像に近い状態の方が「文脈を理解」しやすい。二値化すると情報が失われて逆効果になる。

#### 作成するファイル

| ファイル | 操作 | 内容 |
|---|---|---|
| `scripts/preprocess.py` | 新規 | ImagePreprocessorクラス（2モード対応） |

---

### Step 3: OCR比較テスト（最重要ステップ）

**目的**: 実際の戦前文書で各エンジンの精度を比較し、メインエンジンを決定する

#### 比較対象

| エンジン | 予想精度 | 処理速度 | 特徴 |
|---|---|---|---|
| Gemma 3 12B | 70-85% | 30-120秒/枚 | 文脈理解力が強み。旧字体→現代語変換も一発 |
| Qwen3-VL 8B | 65-80% | 20-90秒/枚 | OCRBenchで高スコア |
| Surya OCR | 50-70% | 5-15秒/枚 | 速い。旧字体認識は弱い可能性 |

#### テスト方法

1. テスト画像を `input/` に3-5枚用意（JACAR等から取得）
2. 正解テキストを手動作成して `training_data/labels/` に配置
3. `ocr_compare.py` で文字一致率・処理速度を比較

#### チェックポイント

- [ ] 旧字体の漢字は正しく読めているか？（例: 「國」「學」「會」）
- [ ] カタカナの認識精度は？
- [ ] 句読点や記号の認識は？
- [ ] 縦書き・右横書きの読み順は正しいか？
- [ ] 処理速度は実用的か？

#### 作成するファイル

| ファイル | 操作 | 内容 |
|---|---|---|
| `scripts/ocr_vision_llm.py` | 新規 | Vision LLM OCR（戦前文書用プロンプト付き） |
| `scripts/ocr_surya.py` | 新規 | Surya OCR ラッパー |
| `scripts/ocr_compare.py` | 新規 | 全エンジン比較実行＋精度計測 |
| `utils/ollama_client.py` | 新規 | Ollama APIラッパー |

---

### Step 4: 後処理

**目的**: OCR出力の旧字体を現代語に変換する

**重要な方針**: Vision LLMを使う場合、プロンプトで「現代語に変換して」と指示すればLLM自身が変換してくれる。後処理が不要になる可能性がある。Step 3の結果を見て判断。

フォールバック用に辞書ベースの変換も実装:

#### 作成するファイル

| ファイル | 操作 | 内容 |
|---|---|---|
| `utils/char_converter.py` | 新規 | 旧字体→新字体辞書（数百エントリ） |
| `utils/kana_converter.py` | 新規 | 歴史的仮名遣い→現代仮名遣い |
| `scripts/postprocess.py` | 新規 | 後処理統合 |

---

### Step 5: パイプライン統合

**目的**: 全体を1つのコマンドで実行できるようにする

```bash
# 使い方の例（uv run で自動的に仮想環境が使われる）

# 1枚の画像をVision LLMで処理
uv run python scripts/pipeline.py input/sample.jpg -e vision_llm -m gemma3:12b

# 右横書きの画像
uv run python scripts/pipeline.py input/rtl_document.jpg --rtl

# フォルダ一括処理
uv run python scripts/pipeline.py input/ -o output/

# Surya OCRで処理（比較用）
uv run python scripts/pipeline.py input/sample.jpg -e surya
```

#### 作成するファイル

| ファイル | 操作 | 内容 |
|---|---|---|
| `scripts/pipeline.py` | 新規 | 全体統合パイプライン（CLI対応） |

---

## 実装の優先順位

| 順位 | ステップ | 理由 |
|---|---|---|
| 1 (最優先) | Step 1: Ollamaインストール + Gemma 3動作確認 | 土台が必要 |
| 2 (高) | Step 3-a: Vision LLM OCRスクリプト | まず1枚読ませて手応えを確認 |
| 3 (高) | Step 3-c: 比較テスト | メインエンジンを確定 |
| 4 (中) | Step 2: 画像前処理 | 精度改善 |
| 5 (中) | Step 4: 後処理 | Vision LLMの結果次第で不要かも |
| 6 (低) | Step 5: 統合パイプライン | 個別が動いてから |

---

## 検証方法

1. `scripts/setup_check.py` で環境構築を確認
2. テスト画像1枚で `scripts/ocr_vision_llm.py` を実行し、戦前文書が読めるか確認
3. `scripts/ocr_compare.py` で各エンジンの精度・速度を比較
4. `scripts/pipeline.py` でフォルダ一括処理が動作することを確認

---

## リスクと対策

| リスク | 対策 |
|---|---|
| Vision LLMの戦前日本語精度が不十分 | 複数モデル比較（Gemma 3, Qwen3-VL）。Surya OCRへフォールバック |
| RAM 8GBで12Bモデルが動かない | gemma3:4b を使用 |
| Vision LLMの処理が遅すぎる | 4Bモデルに切替。バッチ処理実装 |
| 旧字体→新字体辞書が不完全 | Vision LLMに変換を任せる方針にシフト |

---

## 参考リンク

| リソース | URL |
|---|---|
| Ollama公式（Mac版DL） | https://ollama.com/download/mac |
| Gemma 3 on Ollama | https://ollama.com/library/gemma3 |
| Qwen3-VL on Ollama | https://ollama.com/library/qwen3-vl |
| Surya OCR GitHub | https://github.com/datalab-to/surya |
| Ollama Python Client | https://github.com/ollama/ollama-python |
| JACAR（アジア歴史資料センター） | https://www.jacar.go.jp/ |
