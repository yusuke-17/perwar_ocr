## 1. 反復の切り落とし（`utils/ollama_client.py`）

- [ ] 1.1 反復の切り落としを純粋関数として実装する（design D1。戻り値は「切り落とし後のテキスト」と「切り落とした字数」）。仕様「OCR 出力の反復の切り落とし」の 4 Scenario（反復あり・反復なし・空行のみ・正当な繰り返し）をテストで確認する
- [ ] 1.2 `OCRResult` に `trimmed_chars` と `hit_limit` を追加し、`ocr()` が `_call_ollama` の結果に切り落としを適用して返すようにする。偽クライアントで反復テキストを返し、`result.text` が切り落とし後、`trimmed_chars` が正しい字数になることをテストで確認する

## 2. 生成トークン上限と上限到達の検知

- [ ] 2.1 `_DEFAULTS["ocr"]` に `num_predict = 1024` を追加し、`ocr_options()` が 0 以下のとき `num_predict` を渡さないようにする（design D2）。`tests/test_ollama_options.py` に「既定で 1024 が渡る」「0 で渡らない」を追加して確認する
- [ ] 2.2 `_call_ollama` が `done_reason` を返し、`OCRResult.hit_limit` に `done_reason == "length"` を入れる（design D3）。偽クライアントで `done_reason` を切り替え、`hit_limit` が追従することをテストで確認する
- [ ] 2.3 `config.toml` の `[ocr]` のコメント例に `num_predict` と `retry_on_repeat` を追記し、「num_predict は書かないこと」の注意書きを「上限到達は警告が出る」に書き換える。`uv run prewar check` が設定を読めて起動することを確認する

## 3. 反復エラーの分類と再試行

- [ ] 3.1 `OllamaRepeatError` を追加し、`ollama_errors()` で反復検知の `ResponseError`（status 500、メッセージに `repeat`）を翻訳する（design D5）。`tests/test_ollama_options.py` の `test_error_translation` の表に 1 行足し、`test_other_response_errors_pass_through` が引き続き通ることを確認する
- [ ] 3.2 `_DEFAULTS["ocr"]` に `retry_on_repeat = 1` を追加し、`ocr_options()` から除外する読み出し口を作る（design D6）。`ocr_options()` の戻り値に `retry_on_repeat` が含まれないことをテストで確認する
- [ ] 3.3 `OllamaOCRClient.ocr()` にシードを変えた再試行を実装する（design D6）。偽クライアントで「1 回目は `OllamaRepeatError`、2 回目は成功」を再現し、仕様の Scenario「再試行で成功する」「再試行しても失敗する」と、2 回目の `options["seed"]` が 1 回目と違うことをテストで確認する
- [ ] 3.4 `_OCR_ERROR_KINDS` に `repeat` を追加し、`_ocr_pages` で理由 `repeat` を連続失敗に数えないようにする（design D6）。`tests/test_ocr_batch.py` に仕様の Scenario「反復による失敗は打ち切りに数えない」「接続不可は従来どおり打ち切りに数える」を追加して確認する

## 4. 表示とメタ情報

- [ ] 4.1 `_run_ocr_page` で切り落とし・上限到達・再試行の警告を表示する（design D3・D6）。`capsys` で、反復ありのページで字数入りの警告、上限到達のページで `num_predict` の案内、両方無しのページで警告なしになることをテストで確認する
- [ ] 4.2 `MetaOcr` に `repetition_trimmed` と `hit_limit_pages` を追加し、`save_document` が「あるときだけ」`meta.json` に出すようにする（design D4）。`MetaPageFailure.reason` のコメントに `repeat` を足す。`tests/test_ocr_batch.py` のメタ情報テストで、反復ありのときにキーが出て、全ページ正常のときに出ないこと、既存の `test_meta_has_no_pages_section_when_all_succeed` が通ることを確認する
- [ ] 4.3 `_build_record` が `OCRResult` の `trimmed_chars` / `hit_limit` をページ番号付きで `MetaOcr` に集約することをテストで確認する（成功ページの添字は `ok_indices` と対応させ、元のページ番号で記録する）

## 5. 環境確認（`scripts/setup_check.py`）

- [ ] 5.1 Ollama のバージョンを取得して表示する（design D7）。`tests/test_setup_check.py` で、取得成功時にバージョンが表示されること、取得失敗時に「不明」と表示されて合否が変わらないことを確認する

## 6. 実機確認とドキュメント

- [ ] 6.1 `uv run prewar ocr input/1.png` を実行し、所要時間が 20 秒以内、画面に反復の警告（字数つき）と上限到達の警告が出て、`ocr_raw.txt` が反復を含まず、`meta.json` に `repetition_trimmed` と `hit_limit_pages` が出ることを確認する
- [ ] 6.2 実測で反復検知の 500 になった `input/3.png` と `input/5.png` を単独で処理し、シードを変えた再試行で成功するかを記録する。2 枚とも再試行後も失敗するなら `retry_on_repeat` の既定を 0 にし、仕様の「既定値は 1」を 0 に改めて 3.2 の既定も直す
- [ ] 6.3 対話メニューで `input/1.png`〜`10.png` を複数選択して処理し、OCR 全体が 3 分以内に終わり、打ち切りが起きず、失敗ページがあっても理由が `repeat` で記録されることを確認する。結果（所要時間・失敗数）を `survey/batch-slow-failure-survey.md` の末尾に追記する
- [ ] 6.4 `README.md` に `[ocr] num_predict` / `retry_on_repeat` と、反復の警告・上限到達の警告の意味と対処を追記する。`PROGRESS.md` の「直近の作業」と `plan/improvement-ideas.md` の G12 を完了に更新する
- [ ] 6.5 `uv run pytest tests/ pkg/` が全件通ることを確認する
