## 1. 並べ替えの部品（`utils/page_order.py`）

- [x] 1.1 `natural_key` を実装する（design D2）。`tests/test_page_order.py` を新設し、仕様「ページ順の既定は自然順」の各 Scenario（0埋めなし、`pNNN`、スクショ名の時刻1桁/2桁、` (2)`、全角数字）と、`p999`→`p1000`、大文字小文字の混在、拡張子の混在が期待順になることをテストで確認する
- [x] 1.2 `natural_key` の落とし穴をテストで確認する: `²` を含む名前で例外が出ない、`1.png` と `01.png`・全角と半角の同値でも入力の並びを変えて同じ結果になる、NFC と NFD の名前が同じ位置に並ぶ
- [x] 1.3 `list_images` を実装する（design D3・D4）。`tmp_path` に `1.png`、`2.tif`、`3.webp`、`._1.png`、`old.png/`（フォルダ）、`memo.txt` を置き、前の3つだけが自然順で返ることをテストで確認する
- [x] 1.4 `sort_pages` を実装する（design D3・D6）。`os.utime` で更新日時を設定し、`mtime` 指定で古い順になること、更新日時が同じなら自然順になることをテストで確認する
- [x] 1.5 `first_mismatch` を実装する。食い違いありで最初の位置と両方の画像が返ること、食い違いなし・更新日時がすべて同じ・1枚のときに `None` が返ることをテストで確認する

## 2. 設定と引数

- [x] 2.1 `utils/config.py` の `_DEFAULTS` に `batch.order = "name"` を追加し、`config.toml` のコメント例に `[batch] order` を追記する。`CONFIG.get("batch.order")` が `"name"` を返すことを確認する
- [x] 2.2 `add_arguments` に `--order`（`choices=["name", "mtime"]`、`default=None`）を追加する。`tests/test_cli.py` の `OCR_ARG_NAMES` に `order` を足し、有効な値の受理と未知の値の拒否を既存の `--on-page-error` のテストと同じ形で確認する
- [x] 2.3 並べ方を「CLI フラグ > `config.toml` > 既定値」で解決する関数を追加する（design D5）。設定ファイルの値が未知のときに、使える値を示すエラーを出して終了コード 1 になることをテストで確認する

## 3. パイプラインへの組み込み（`scripts/ocr_vision_llm.py` ほか）

- [x] 3.1 `IMAGE_EXTENSIONS` を削除し、`select_image_interactive`・`select_images_batch`・`load_folder_images` の列挙を `list_images` に置き換える。`:228` のコメントと `load_folder_images` の docstring を実態に合わせて直す。`uv run pytest tests/` が通ることを確認する
- [x] 3.2 `scripts/clean.py` の `IMAGE_EXTENSIONS` を `ollama_client.SUPPORTED_EXTENSIONS` の参照に置き換える。`grep -rn "IMAGE_EXTENSIONS" scripts utils` が0件になることを確認する
- [x] 3.3 番号付き一覧の表示を追加し、`process_batch` の `対象:` 行を置き換える（design D8）。`tests/test_ocr_pipeline.py` の `対象:` を確認しているテストを新しい表示に更新し、1枚のときは一覧が出ないことも確認する
- [x] 3.4 フォルダ指定（結合）に、並べ方の適用と食い違いの警告を組み込む（design D7）。仕様の Scenario「フォルダ指定で食い違いがある」「食い違いがない」「更新日時がすべて同じ」「更新日時の古い順を実行時に指定する」をパイプラインのテストで確認する（警告の有無、結合順、終了コード 0）
- [x] 3.5 `--separate` と更新日時順の指定では警告が出ないことをテストで確認する
- [x] 3.6 対話メニューの複数選択に、並べ方の適用と3択（このまま進む / 更新日時の古い順に並べ替えて進む / やめる）を組み込む。`questionary` を差し替えたテストで、3つの選択それぞれの結合順と終了コード（やめる＝OCR なし・保存なし・1）を確認する
- [x] 3.7 撮りためを「撮った順のまま渡す」形に変える: `process_folder` に画像リストを直接渡せる口を足し、`cmd_shoot` から使う。`utils/screen_capture.py` の `sorted(captured)` を外す。設定が `mtime` でも撮った順で結合され、警告が出ないことをテストで確認する（`screen_capture.shoot_session` を差し替える）

## 4. 仕様のシナリオを通しで確認するテスト

- [x] 4.1 `1.png`〜`12.png` のフォルダを処理し、結合後の本文と保存された `source_NN` が 1→12 の順になることを確認する（本文は旧字体・カタカナ書きの文字列を使う）
- [x] 4.2 同じフォルダを旧形式出力の指定で処理し、`1-12_modern.txt` が作られることを確認する
- [x] 4.3 `.tif` と `.webp` の実画像を OpenCV で作り、前処理を有効にしたまま読み込めることを確認する（design D4 の前提の確認）

## 5. ドキュメント

- [x] 5.1 `README.md` を更新する: 複数画像の並び順（自然順）、`--order`、`[batch] order`、食い違いの警告と対話での選択、`.tif` / `.webp` が対象に加わったこと、複数ページ TIFF の注意。記載したコマンド例が `uv run prewar ocr --help` の表示と一致することを確認する
- [x] 5.2 `PROGRESS.md` に今回の作業を追記し、`plan/improvement-ideas.md` の D5 を完了表示にする（テスト件数は実測値を書く）

## 6. 最終確認

- [x] 6.1 `uv run pytest tests/ pkg/` が全件通ることを確認する
- [x] 6.2 `openspec validate d5-page-order-sort --strict` が通ることを確認する
- [x] 6.3 実物の `input/` で列挙結果を確認する（OCR は実行しない）: `list_images(Path("input"))` が `1.png`〜`32.png` の順を返し、`first_mismatch` が `None` を返すこと
