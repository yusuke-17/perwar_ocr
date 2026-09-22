## Why

使われていない依存・設定・コード・古い記述が残っており、「効くと誤解する設定」「使っていないのに 500MB 超を占める依存」「実在しないコマンドや数値を案内する文書」が混乱の元になっている。
G1〜G7 で足回りを固めた今、F1（ローカルRAG）など新機能に進む前に土台を掃除しておく。
調査結果は `survey/g8-dead-code-survey.md` にまとめてある。

## What Changes

**依存パッケージ**
- `requests` を依存から削除する（import 0件、他パッケージからも要求されていない）
- `surya-ocr` を必須依存から任意の追加依存（extra `surya`）へ移す。これで torch・transformers 等の重量級依存が通常の `uv sync` で入らなくなる
- `pillow` を依存から削除する（直接 import 0件。surya 経由でのみ必要）

**環境確認（`prewar check`）**
- Surya OCR 未導入を失敗扱いしない。任意機能として「未導入」と表示し、合否の集計から外す
- 依存パッケージ確認の一覧を、実際に使っている必須依存に合わせる（Pillow を外し、jaconv 等の抜けを足す）

**起動コマンド**
- **BREAKING**: 旧コマンド `prewar-ocr` / `prewar-library` を削除し、統合CLI `prewar` に一本化する
- 旧コマンド専用のラッパー（`parse_args` / `main` / `__main__` ブロック / library の `add_arguments`・`run`）を削除する
- 旧 `prewar-library` のヘルプにだけあった検索構文の説明を `prewar search --help` へ移す

**デッドコード**
- 設定 `chunk.overlap` を削除する（読み込むだけで分割処理に一切効いていない）
- `OCRResult.raw_response` と、それを作るだけの処理を削除する（誰も読まない）
- テストからしか呼ばれない `OllamaOCRClient.is_available()` と `ModernizeResult.ok` を削除する
- ルートの `main.py`（`uv init` の雛形）と、役目を終えた `.gitkeep`（plan/ scripts/ utils/）を削除する
- `.gitignore` に `.pytest_cache/` と `.ruff_cache/` を追加する

**ドキュメント**
- 実態と食い違う記述を直す（senzen_word README の字数・パターン数・変換例、README の配置パス、Surya の位置づけ、誤読辞書の件数など）
- 未記載の機能を足す（`prewar diff` / `prewar clean`、config のセクション、フォルダ構成表）
- archive 済みの変更への古いパス参照を直す
- 初期計画書 `plan/implementation_plan.md` には「現状と乖離した歴史的文書」である旨の注記を付ける（本文は書き換えない）

## Capabilities

### New Capabilities
- `cli`: 統合CLI `prewar` を唯一の起動コマンドとすること、および環境確認（`prewar check`）が必須機能だけで合否を判定し任意機能の未導入を失敗扱いしないこと

### Modified Capabilities
（なし。`ocr-pipeline` と `library-search` の要求は変わらない。`chunk.overlap` の削除は動作を変えない）

## Impact

- **依存**: `pyproject.toml`、`uv.lock`。`uv sync` 後の `.venv` は約 700MB → 200MB 前後に縮む見込み
- **コード**: `scripts/setup_check.py`、`scripts/cli.py`、`scripts/ocr_vision_llm.py`、`scripts/library.py`、`scripts/postprocess.py`、`utils/ollama_client.py`、`utils/text_modernizer.py`、`utils/config.py`、`config.toml`
- **テスト**: `tests/test_ollama_options.py`（`is_available` のテスト削除）、`tests/test_modernize_resilience.py`（`.ok` の置き換え）、`tests/test_cli.py` ほか（環境確認と起動コマンドのテスト追加）
- **ドキュメント**: `README.md`、`CLAUDE.md`、`PROGRESS.md`、`openspec/config.yaml`、`plan/improvement-ideas.md`、`plan/implementation_plan.md`、`pkg/senzen_word/README.md`
- **利用者への影響**: `uv run prewar-ocr` / `uv run prewar-library` は使えなくなる。`uv run prewar ocr` / `uv run prewar search` 等に置き換える。Surya を使いたい場合は `uv sync --extra surya` が必要になる
- **影響しないもの**: OCR・正規化・口語化・保存・検索の動作と出力、`pkg/senzen_word/` のコード（README のみ修正）
