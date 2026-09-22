## 1. 依存パッケージの整理

- [x] 1.1 変更前の基準を記録する: `uv run pytest tests/ pkg/ -q` の件数（調査時 373件）と `du -sh .venv` のサイズ（調査時 約700MB）をメモする
- [x] 1.2 `uv remove requests pillow surya-ocr` を実行し、`uv add --optional surya "surya-ocr>=0.17.1"` で surya を extra `surya` に移す。`pyproject.toml` の `dependencies` に requests・pillow・surya-ocr が無く、`[project.optional-dependencies]` に `surya` があることを確認する
- [x] 1.3 `git diff uv.lock` で、削除した3つとその推移依存以外のパッケージのバージョンが変わっていないことを確認する
- [x] 1.4 `uv sync` を実行し、`du -sh .venv` が大きく縮み、`uv run python -c "import torch"` が ImportError になることを確認する。この時点で `uv run pytest tests/ pkg/ -q` が 1.1 と同じ件数で全件通ることを確認する

## 2. 環境確認（`prewar check`）

- [x] 2.1 `scripts/setup_check.py` の `check_packages()` の確認対象を design D3 の8パッケージにそろえ（Pillow を外す）、欠けていたときの案内を `uv sync` にする
- [x] 2.2 `check_surya()` を `importlib.util.find_spec("surya")` による有無判定に変え、未導入なら「未導入（任意）」と `uv sync --extra surya` の案内を出す
- [x] 2.3 `main()` の集計を必須項目と任意項目に分け、終了コードを必須項目だけで決める。サマリーでは任意項目を ✓ か −（未導入・任意）で表示する。`if __name__` ブロックを削除する（`main()` は対話メニューが使うので残す）
- [x] 2.4 `tests/test_setup_check.py` を新設し、各 `check_*` を monkeypatch で差し替えて次を確かめる: 必須が揃い Surya 未導入で 0、必須の1つ（Ollama 接続）が欠けたら 1、確認対象に PIL が含まれず jaconv が含まれる。`uv run pytest tests/test_setup_check.py -q` が通ることを確認する
- [x] 2.5 `uv run prewar check` を実機で実行し、Surya が「未導入（任意）」と表示され、Ollama 起動中なら終了コード 0 で終わることを確認する（`echo $?`）

## 3. 旧コマンドの削除

- [x] 3.1 `library.py` に検索構文の説明と `prewar search ...` 形式の使用例をまとめた定数を作り、`cli.py` の `search` サブパーサで `epilog` と `RawDescriptionHelpFormatter` を使って表示する。`uv run prewar search --help` に OR・NOT・`原文:`・3文字以上の注意が出ることを確認する
- [x] 3.2 `pyproject.toml` の `[project.scripts]` を `prewar` だけにし、`uv sync` 後に `uv run prewar-ocr` がコマンド未検出で失敗することを確認する
- [x] 3.3 `scripts/ocr_vision_llm.py` と `scripts/postprocess.py` から `parse_args` / `main` / `if __name__` ブロックを削除し、`scripts/library.py` からは加えて `add_arguments` と `run` も削除する。`grep -rn "parse_args\|def main" scripts/` で `cli.py` と `setup_check.py` 以外に残っていないことを確認する
- [x] 3.4 各スクリプト冒頭の docstring と `cli.py` の docstring・コメントにある旧コマンド（`prewar-ocr` / `prewar-library` / `python scripts/...`）を `prewar` のサブコマンドに書き換える。`grep -rn "prewar-ocr \|prewar-library\|python scripts/" scripts/` が0件になることを確認する
- [x] 3.5 `tests/test_cli.py` に次のテストを追加する: `pyproject.toml` の `[project.scripts]` が `prewar` だけ、`search` サブパーサのヘルプ文字列に OR・NOT・`原文:`・3文字の注意が含まれる。`uv run pytest tests/test_cli.py -q` が通ることを確認する

## 4. デッドコードの削除

- [x] 4.1 `chunk.overlap` を削除する（`utils/config.py` の `_DEFAULTS`、`config.toml` のコメント行、`utils/text_modernizer.py` の `DEFAULT_CHUNK_OVERLAP` と `__init__` の引数・属性）。`grep -rn "overlap" utils scripts tests config.toml` が0件になることを確認する
- [x] 4.2 `OCRResult.raw_response` を削除し、`_call_ollama` を本文の文字列だけを返す形にする。`grep -rn "raw_response\|raw_info" utils scripts tests` が0件になることを確認する
- [x] 4.3 `OllamaOCRClient.is_available()` と `_check_model_available` の `force` 引数を削除し、`tests/test_ollama_options.py` の `test_is_available_always_asks` を削除する
- [x] 4.4 `ModernizeResult.ok` を削除し、`tests/test_modernize_resilience.py` の `result.ok is True` を `result.failures == []` と `result.aborted is False` の確認に置き換える
- [x] 4.5 ルートの `main.py` と `plan/.gitkeep`・`scripts/.gitkeep`・`utils/.gitkeep` を `git rm` し、`.gitignore` に `.pytest_cache/` と `.ruff_cache/` を追加する。`input/` `output/` `library/` の `.gitkeep` は残っていることを確認する
- [x] 4.6 `uvx vulture scripts utils --min-confidence 60` と `uvx ruff check --select F401,F841,F811 scripts utils tests` がともに検出0件になることを確認する
- [x] 4.7 `uv run pytest tests/ pkg/ -q` が全件通ることを確認し（件数は 1.1 から `is_available` の1件減、2.4・3.5 の追加分増）、ここまでをコミットする

## 5. ドキュメントの修正

- [x] 5.1 `pkg/senzen_word/README.md` を直す: 旧字体の字数・歴史的仮名遣いのパターン数・`convert` の例を実際に計測・実行した値にし、`find_*`・`get_kanji_table`・`tools/gen_hentaigana.py`・テストの実行方法を追記する。記載した例をすべて `uv run python -c` で実行して一致を確認する
- [x] 5.2 `README.md` を直す: 後方互換の注記を旧コマンドからの置き換え表に差し替え、配置パス（`~/Desktop/...`）、`plan/` の説明、フォルダ構成表（`openspec/`・`tests/`・`config.toml`）、`prewar diff` / `prewar clean` の説明、Surya を使う場合の `uv sync --extra surya` を反映する。記載したコマンドを `--help` で実在確認する
- [x] 5.3 `CLAUDE.md` を直す: Surya の位置づけ（任意の追加依存・現状 OCR には未使用）、旧コマンド残存の記述の削除、対話メニューの列挙（差分表示・データ整理）、config のセクション列挙（preprocess / progress / batch / diff）
- [x] 5.4 `openspec/config.yaml` の Surya の記述を 5.3 と同じ位置づけに直す
- [x] 5.5 `plan/improvement-ideas.md` を直す: archive 済み変更へのパス、A4 の誤読辞書の件数（`utils/text_normalizer.py` で数え直す）、A2 の「Surya も依存済み」を「extra `surya` で導入可能」に、G9 の設定キー名が既存の `batch.abort_after_consecutive_failures` と紛らわしい点の注記、G8 を実装済みに移す
- [x] 5.6 `plan/implementation_plan.md` の冒頭に「OpenSpec 導入前の初期計画。現状の構成とは異なる」旨の注記を入れる
- [x] 5.7 `PROGRESS.md` を直す: archive 済み変更へのパス、コマンド一覧への `prewar diff` / `prewar clean` の追加、G8 の完了と次の候補の更新
- [x] 5.8 `git grep -n "prewar-ocr \|prewar-library\|search-index-original-text/\|search-query-expression/"` で、archive 配下と `survey/` 以外に古い参照が残っていないことを確認する

## 6. 最終確認

- [x] 6.1 `uv run pytest tests/ pkg/ -q` が全件通り、`uv run prewar check`・`uv run prewar search --help`・引数なしの `uv run prewar` のメニュー表示が期待どおりであることを確認する
- [x] 6.2 `du -sh .venv` を 1.1 の値と比べて削減量を記録し（PROGRESS.md に1行）、ドキュメント修正をコミットする
