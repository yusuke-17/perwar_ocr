# G8 調査レポート: デッドコード・不要依存の整理

調査日: 2026-09-22
対象: `pyproject.toml` の依存、`scripts/` `utils/` `pkg/senzen_word/` のコード、ドキュメント類
位置づけ: `/opsx:propose` の参照材料。設計の確定はここでは行わない。
使用ツール: `uvx vulture`、`uvx ruff check --select F401,F841,F811`、`uv tree`、手動 grep

---

## 1. 結論（先に要点）

- **`plan/improvement-ideas.md` の G8 記述（overlap / requests / surya）は3件とも事実**。
  加えて調査で `pillow` 未使用、`OCRResult.raw_response` 書き捨て、`main.py` 残置などが見つかった。
- **効果が最も大きいのは surya-ocr の optional 化**。surya 本体は 1.2MB だが、torch（377MB）・
  transformers（49MB）・sympy（41MB）等を引き込み、`.venv` 700MB の **7割超**を占める。
  コード上は `prewar check` の「import できるか」判定にしか使われておらず、OCR 本線から到達しない。
- **コード側のデッドコードは少ない**。vulture/ruff の検出は本体で3件、senzen_word で0件。
  190個の定義を手動分類しても「確実に不要」は `chunk.overlap` と `raw_response` の2系統のみ。
- **旧エントリポイント `prewar-ocr` / `prewar-library` は薄いラッパー層だけが重複**。
  本体ロジックは `cli.py` と共有済み。残す・消すは方針判断（後方互換の明記が3箇所ある）。
- **ドキュメントの陳腐化が目立つ**。senzen_word README の数値ズレ、`prewar diff`/`clean` の未記載、
  archive 済み change への旧パス参照など。G8 の範囲に含めるか、別途整理するか判断が要る。

---

## 2. 依存パッケージ（`pyproject.toml`）

### 2-1. 判定一覧

| パッケージ | 直接 import | 到達経路 | 判定 |
|---|---|---|---|
| ollama | `utils/ollama_client.py:112,119,137`（遅延） | OCR・口語体変換の中核 | 必須 |
| httpx | `utils/ollama_client.py:136`（遅延） | `httpx.TimeoutException` を直接 except | 必須（ollama の推移依存だが直接 import があるため明示宣言は妥当。`tests/test_ollama_options.py:136-142` に回帰テストあり） |
| questionary | `cli.py:28`, `clean.py:26`, `ocr_vision_llm.py:34`, `screen_capture.py:26` | 対話メニュー全経路 | 必須 |
| opencv-python-headless | `utils/image_preprocessor.py:23` | `ocr_vision_llm.py:703→334→362`、`preprocess.enabled` 既定 True | 必須 |
| numpy | `utils/image_preprocessor.py:24` | 同上 | 必須 |
| jaconv | `utils/text_normalizer.py:31` | 正規化 | 必須 |
| rich | `utils/progress.py:67,93`（遅延） | `progress.enabled` 既定 True | 必須 |
| senzen-word | `text_normalizer.py:33-34`, `postprocess.py:41` | 正規化の中核（workspace） | 必須 |
| **surya-ocr** | `scripts/setup_check.py:105` のみ | `prewar check` の import 確認のみ | **optional 化候補（最優先）** |
| **pillow** | **0件** | surya 経由でのみ必要。`setup_check.py:30` の存在確認文字列だけ | **削除候補**（surya と同時に） |
| **requests** | **0件** | `uv tree --invert` で親は prewar-ocr のみ | **削除候補（確実）** |
| pytest（dev） | tests 全体 | — | 必須 |

### 2-2. surya-ocr の実態

到達経路は1本だけ。

```
scripts/cli.py:139  p_check.set_defaults(func=setup_check.run)     # prewar check
scripts/cli.py:240  "環境確認": setup_check.main                    # 対話メニュー
  └→ setup_check.py:143  results["surya"] = check_surya()
     └→ setup_check.py:105  from surya.recognition import RecognitionPredictor   # import して未使用
```

- `ocr_vision_llm.py` から surya への参照はゼロ。OCR は GLM-OCR（Ollama）のみ。
- `_DEFAULTS`（`utils/config.py`）にも `config.toml` にもエンジン切替キーは無い。
- `check_surya()` は無条件で走り、`setup_check.py:156-161` の集計に含まれるため、
  **surya が無いと `prewar check` が exit 1 になる**。optional 化するなら「未導入ならスキップ」に変える必要がある。
- ドキュメント上の位置づけ: `CLAUDE.md:10`、`openspec/config.yaml:12` が「補助・比較用」と記載。
  `README.md` と `openspec/specs/` には言及なし。`plan/improvement-ideas.md:27`（A2）で「未実装」と明記。

### 2-3. surya が引き込む重量級依存（`uv tree --package surya-ocr`、実測サイズ）

| パッケージ | サイズ | surya 以外の利用 |
|---|---:|---|
| torch | 377MB | なし |
| transformers | 49MB | なし |
| sympy（torch 経由） | 41MB | なし |
| PIL | 13MB | なし（自前 import 0件） |
| tokenizers | 9.1MB | なし |
| networkx（torch 経由） | 7.8MB | なし |
| virtualenv（pre-commit 経由） | 7.3MB | なし。開発ツールが実行時依存に混入している |
| pypdfium2 | 5.7MB | なし |
| cv2 / numpy | 99MB / 23MB | **自前コードで使用**（残る） |

概算で **500MB 超**が「import 可否を確認するだけ」の依存。

### 2-4. requests が入っていた理由

`plan/implementation_plan.md:130` に「surya-ocr は内部で requests を使うが依存宣言に含まれていない」とあり、
これが追加理由。surya-ocr 0.17.1 のメタデータに requests は無く、**前提はすでに無効**。

---

## 3. コードのデッドコード（scripts/ utils/）

### 3-1. 確実に不要

| 対象 | 箇所 | 根拠 |
|---|---|---|
| `chunk.overlap` 設定 | `utils/config.py:43`、`config.toml:20`、`utils/text_modernizer.py:38,129,134` | `self.chunk_overlap` に格納後、**読む箇所が repo 全体で0件**。`_split_text`（`:250-298`）は文単位の greedy 結合で前チャンク末尾を重ねる処理が無い。設定しても何も変わらない |
| `OCRResult.raw_response` と `raw_info` 生成 | `utils/ollama_client.py:40,205,214,295-302` | `_call_ollama` がタプルで返し詰めるが `.raw_response` を読むコードは0件。meta.json（`library_writer.py:239-241`）にも書かれない。消せば `_call_ollama` は `str` 返却に単純化できる |
| 旧 argparse epilog の使用例 | `scripts/ocr_vision_llm.py:163-171`、`scripts/postprocess.py:181-187` | `uv run python scripts/...py` 形式で、現行の `uv run prewar ocr` / `prewar fix` と食い違う。旧エントリ経由でしか表示されない |

### 3-2. 要判断

**テストからのみ使われる**

| 対象 | 箇所 | 使用テスト |
|---|---|---|
| `OllamaOCRClient.is_available()` | `utils/ollama_client.py:218` | `tests/test_ollama_options.py:255-261` のみ |
| `ModernizeResult.ok` | `utils/text_modernizer.py:103-106` | `tests/test_modernize_resilience.py:169` のみ |

残すなら「テスト用API」と明記、消すなら該当テストも削除。

**後方互換エントリポイント `prewar-ocr` / `prewar-library`**（`pyproject.toml:29-30`）

本体ロジックは `cli.py` と共有済みで、旧エントリ専用なのは以下のラッパー層のみ。

| ファイル | 共有（cli.py が使う） | 旧エントリ専用 |
|---|---|---|
| `ocr_vision_llm.py` | `add_arguments`（:66）、`run`（:858） | `parse_args`（:158-173）、`main`（:888-890）、`if __name__`（:893） |
| `library.py` | `add_*_arguments`（:41/51/60）、`cmd_*`（:146/166/214） | `add_arguments`（:97-109）、`parse_args`（:112-140、検索構文ヘルプ約25行）、`run`（:314-322）、`main`（:325-326） |
| `postprocess.py`（**scripts 未登録**） | `add_arguments`（:141）、`run`（:193） | `parse_args`（:177-190）、`main`（:274-275）。到達手段は `uv run python scripts/postprocess.py` のみで現行ドキュメントに案内なし |

- 旧 `parse_args` / `main` を参照するテストは0件（`tests/test_cli.py` は `cli.build_parser()` 経由のみ）。
- 後方互換の明記: `README.md:77`、`CLAUDE.md:15`、`scripts/cli.py:22`（docstring）。`openspec/specs/` に縛りは無い。
- 削除するなら上記3箇所 + `pyproject.toml:29-30` を同時に更新。

### 3-3. 誤検知

`scripts/setup_check.py:105` の `RecognitionPredictor` unused import は「import できるか」の意図的プローブ。
surya を optional 化するなら `importlib.util.find_spec("surya")` に置換、依存ごと外すなら関数ごと削除。

### 3-4. 到達性確認（すべて到達、問題なし）

`clean.py` / `postprocess.py` / `diff_viewer.py` / `setup_check.py` は `cli.py` から到達。
`screen_capture.py` は `ocr_vision_llm.py:63`（`prewar shoot`）、`terminal.py` は `library.py:35` と `diff_viewer.py:34`、
`progress.py` は `ocr_vision_llm.py:60` と `text_modernizer.py:30` から到達。

### 3-5. `_DEFAULTS` 25キーの読み出し状況

25キー中、効いていないのは **`chunk.overlap` の1つだけ**。他は全て読み出し先あり。
補足: `config.toml:7-9` の `[models]` は既定値と同一値を書いている（「差分のみ」方針からすると冗長だが害なし）。

### 3-6. tests/ の共通ヘルパー

`tests/fakes.py` の4つ（`FakeClient` / `StubModernizer` / `MODERN_MARK` / `EchoModernizer`）と
各テストファイルのヘルパーは全て使用中。未使用は0件。

---

## 4. pkg/senzen_word/

- vulture / ruff とも**検出ゼロ**。src 内の全関数は src 内または pkg/tests から参照されている。
- `dependencies = []` は本当にゼロ（標準ライブラリのみ）。
- `tools/gen_hentaigana.py` は `hentaigana.json`（285字）の生成ツール。再生成結果は現行 JSON と**完全一致**。
  `tests/test_hentaigana.py:85-146` がドリフト検知している。ただし `pkg/senzen_word/README.md` に言及なし。
- 本体（scripts/ utils/）から未使用の公開API: `convert()` / `find()` / `find_old_kanji` / `get_kanji_table` /
  `KANA_MAPPINGS` 等。PyPI 公開パッケージなので削除対象ではない（事実の記録のみ）。

---

## 5. ドキュメント・リポジトリの陳腐化（G8 に含めるか要判断）

### 5-1. 事実と食い違う記述

| 場所 | 記述 | 実際 |
|---|---|---|
| `pkg/senzen_word/README.md:33` | 旧字体→新字体 318字 | 384字（joyo 372 + jinmei 9 + variants 3） |
| `pkg/senzen_word/README.md:34` | 歴史的仮名遣い 109パターン | 92パターン |
| `pkg/senzen_word/README.md:18` | `convert("國會ニ於テ")` → `"国会にて"` | 実行結果は `"国会に於テ"` |
| `README.md:38`, `plan/implementation_plan.md:118` | `cd ~/Desktop/prewar-ocr` | 実際は `~/prd/prewar-ocr` |
| `README.md:311` | `plan/` = 「実装計画」 | `CLAUDE.md:47` は「改善案バックログ」 |
| `CLAUDE.md:9` | Surya OCR（補助・比較用） | Surya を使う OCR 経路は存在しない |
| `plan/improvement-ideas.md:29`（A4） | 誤読辞書「47パターン＋文脈2」 | `text_normalizer.py:45-56` は 6パターン＋文脈2 |

### 5-2. 存在しないパス・キーへの言及

| 場所 | 記述 | 実際 |
|---|---|---|
| `PROGRESS.md:78`, `plan/improvement-ideas.md:82` | `openspec/changes/search-index-original-text/` | `openspec/changes/archive/2026-08-24-search-index-original-text/` |
| `plan/improvement-ideas.md:41` | `openspec/changes/search-query-expression/` | `openspec/changes/archive/2026-08-31-search-query-expression/` |
| `plan/improvement-ideas.md:84`（G9） | `chunk.abort_after_consecutive_failures` | `_DEFAULTS` に未定義（未実装の提案なら妥当だが、実在する `batch.abort_after_consecutive_failures` と紛らわしい） |
| `plan/implementation_plan.md` 多数 | `models/`, `scripts/ocr_surya.py`, `ocr_compare.py`, `pipeline.py`, `utils/char_converter.py` 等 | いずれも存在しない（2026-02 の初期計画） |
| `survey/prewar_japanese_ocr_roadmap.md` 多数 | `requirements.txt`, `Dockerfile` 等 | uv 移行前の構成案 |

### 5-3. 記述不足

- `README.md`, `CLAUDE.md:15-16`, `PROGRESS.md:135-141`: **`prewar diff` / `prewar clean`** が未記載
  （`cli.py:124-137` に定義、対話メニューにもある）。
- `CLAUDE.md:45`: config.toml のセクション列挙に `preprocess` / `progress` / `batch` / `diff` が無い。
- `README.md:301-312` フォルダ構成表に `openspec/`, `tests/`, `config.toml` が無い。
- `pkg/senzen_word/README.md`: `find_*`、`get_kanji_table`、`tools/gen_hentaigana.py`、テスト実行方法の記載なし。

### 5-4. リポジトリ内の不要ファイル（`git ls-files`）

| ファイル | 根拠 |
|---|---|
| **`main.py`**（ルート） | `uv init` テンプレート（`print("Hello from prewar-ocr!")`）。どこからも参照なし。scripts/utils/tests/pkg 以外にある唯一の .py |
| `plan/.gitkeep`, `scripts/.gitkeep`, `utils/.gitkeep` | 各ディレクトリに追跡ファイルがあり役目を終えている。`input/ output/ library/` の `.gitkeep` は必要 |
| `plan/implementation_plan.md` | 中身がほぼ現状と乖離。`PROGRESS.md:153` で「OpenSpec 導入前の設計文書」として意図的残置と注記あり |
| `.gitignore` | `.pytest_cache/`, `.ruff_cache/` のパターンが無い（各キャッシュ内の自前 .gitignore で偶然除外） |

---

## 6. 提案スコープ案（`/opsx:propose` の叩き台）

**コア（G8 本来の範囲、コスト小）**

1. `requests` を依存から削除
2. `surya-ocr` を `[project.optional-dependencies]`（例: `surya`）へ移動、`pillow` は削除。
   `check_surya()` は「未導入ならスキップ（集計に含めない）」に変更。`CLAUDE.md:9-10` と `openspec/config.yaml:12` の記述も修正
3. `chunk.overlap` を削除（config.py / config.toml / text_modernizer.py）。実装する案もあるが、
   文単位分割で欠落は起きていないため削除が妥当
4. `OCRResult.raw_response` と `raw_info` を削除、`_call_ollama` を `str` 返却に単純化
5. ルート `main.py` と `plan/ scripts/ utils/` の `.gitkeep` を削除
6. `.gitignore` に `.pytest_cache/` `.ruff_cache/` を追加

**判断が必要**

- 旧エントリ `prewar-ocr` / `prewar-library` を残すか消すか（消すなら 3-2 の箇所を一括更新）
- `is_available()` / `ModernizeResult.ok` をテスト用として残すか
- 5-1〜5-3 のドキュメント修正を G8 に含めるか、別変更にするか

**検証方法**

- `uv sync` 後に `uv run pytest tests/ pkg/`（現在 373件）が全通過すること
- `uv run prewar check` が surya 未導入でも exit 0 になること
- `du -sh .venv` で削減量を確認（目安: 700MB → 200MB 前後）
