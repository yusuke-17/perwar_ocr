# Tasks

## 1. NDLOCR-Lite の取り込みと依存

- [ ] 1.1 `git submodule add` で NDLOCR-Lite を `vendor/ndlocr-lite` に置き、タグ `1.3.1`（コミット `6feccb2`）に固定して `.gitmodules` に `shallow = true` を書く（design D2）。`git -C vendor/ndlocr-lite describe --tags --exact-match` が `1.3.1` を返すこと、`src/model/` に ONNX が 4 本あること、別の場所に clone して `git submodule update --init --depth 1` で同じものが取れることを確認する
- [ ] 1.2 `uv add "onnxruntime>=1.23.2" pillow pyyaml lxml networkx tqdm` で依存を足し、`uv.lock` で numpy が 2.4.2 以上のまま解決されること、`uv run python` から `vendor/ndlocr-lite/src` を `sys.path` の末尾に足して `import ocr` できること、プロジェクトに `ocr`・`config`・`model`・`version`・`deim`・`parseq` という名前のトップレベルモジュールが無いことを確認する。既存のテストが全件通ることも確認する

## 2. 出力の整形（純粋関数、新規 `utils/ndlocr_client.py`）

- [ ] 2.1 `shape_ndlocr_lines(lines)` を実装する（design D3: 読み順のまま・非 ASCII に隣り合う半角空白の除去・向きごとの最大長の 0.9 倍未満の行の後で改行・真下に続く行とは改行しない・空の行は捨てる）。実機 JSON の形だけを写した架空の行データで、仕様「NDLOCR-Lite の出力の整形」の 5 Scenario（列の連結・見出し・空白・段落の終わり・分かれた列）と、英字どうしの空白が残ること、横書きの行（ページ番号）が混ざっても縦書きの最大長が乱れないことを `tests/test_ndlocr_client.py` で確認する
- [ ] 2.2 低信頼度の行数を数える関数を実装し（`confidence < 閾値`、design D4）、閾値ちょうどは数えないこと・行が無いと 0 になることをテストで確認する

## 3. NDLOCR-Lite の呼び出し（`NdlocrLiteClient`）

- [ ] 3.1 `[ndlocr]` セクション（`path = "vendor/ndlocr-lite"`・`low_confidence = 0.7`）を `_DEFAULTS` に追加し、`config.toml` のコメント例に追記する。`ocr_options()` に混ざらないこと、相対パスがプロジェクト直下から解決されることをテストで確認する
- [ ] 3.2 画像の検証（存在・拡張子）を `OllamaOCRClient._validate_image` から共通関数に切り出し、両クライアントから使う。既存の `tests/test_ollama_options.py` が無修正で通ることを確認する
- [ ] 3.3 `NdlocrLiteClient.ocr()` を実装する（design D2: `backend=` で差し替え可能な読み込み・認識の口、モデルは初回だけ読み込み、Pillow で RGB 配列にして `_run_ocr_on_image_array(..., save_viz=False)` を呼ぶ、行のリストを整形、`OCRResult` に `low_confidence_lines` と `engine_version` を入れる）。`OCRResult` に 2 項目を既定値つきで追加する。手書きの偽バックエンドで、本文・`model == "ndlocr-lite"`・`trimmed_chars == 0`・`hit_limit is False`（仕様「NDLOCR-Lite の出力は切り落とさない」「NDLOCR-Lite には上限の警告が出ない」）と、2 枚読んでもバックエンドの読み込みが 1 回だけであること（仕様「複数枚でモデルを読み直さない」）をテストで確認する
- [ ] 3.4 失敗の翻訳を実装する（`NdlocrNotInstalledError`・`NdlocrError`、ファイルの有無と import の事前確認は成功したときだけ覚える）。偽バックエンドで、ソースが無い・モデルが足りない・import に失敗する（依存不足）・認識中に例外が出るを再現し、それぞれの例外と、未導入のメッセージに `git submodule update --init --depth 1` と `uv sync` が入ること、失敗した事前確認は覚えずに次も確かめることをテストで確認する
- [ ] 3.5 版の取得（`git -C <path> describe --tags --exact-match`、取れなければ「不明」、1 クライアント 1 回、`version_reader=` で差し替え可能）を実装し、「`1.3.1` を返す」「git が無い」「タグの無いコミット」をテストで確認する
- [ ] 3.6 上流との結合テストを書く（design D8）: `vendor/ndlocr-lite` が取得済みのときだけ、テスト内で描いた合成の縦書き画像を本物の NDLOCR-Lite で読み、行のリストのキーと型（`text`・`confidence`・`isVertical`・`boundingBox`）が整形の前提どおりで、本文が空でないことを確認する。取得していない環境では skip されることも確認する

## 4. パイプラインへの組み込み（`scripts/ocr_vision_llm.py`）

- [ ] 4.1 `_DEFAULTS["models"]["ocr"]` を `"ndlocr-lite"` にし、`_create_ocr_client` でエンジン名に応じて `NdlocrLiteClient` / `OllamaOCRClient` を作る。NDLOCR-Lite で `--prompt` が指定されたら無視する旨を表示する。仕様「OCR エンジンの選択」の 3 Scenario（既定・実行時に `glm-ocr`・設定で `glm-ocr`）を `tests/test_ocr_pipeline.py` で確認し、既定値を前提にした既存テストがあれば直す
- [ ] 4.2 `_OCR_ERROR_KINDS` に NDLOCR-Lite の 2 例外を追加する（未導入→`model`・表示「OCRエンジン未導入」、認識中のエラー→`unknown`）。仕様の Scenario「NDLOCR-Lite が導入されていない」（3 枚で打ち切り）・「認識中にエラーが出る」を `tests/test_ocr_batch.py` で確認する
- [ ] 4.3 `_preprocess_images` でエンジンが `ndlocr-lite` なら前処理をしないようにする（design D5）。仕様「エンジンごとの画像前処理の適用」の 2 Scenario を、前処理が有効な設定で確認する（NDLOCR-Lite では記録に前処理の情報が残らない／GLM-OCR では残る）
- [ ] 4.4 `_warn_ocr_quality` に低信頼度の警告を足し、`MetaOcr` に `low_confidence_lines` と `engine_version` を加え、`_build_record` が元のページ番号で集め、`save_document` があるときだけ出すようにする（design D4）。仕様「認識の信頼度が低い行の警告」の 2 Scenario と「使ったエンジンの記録」、GLM-OCR の記録に `engine_version` が出ないことをテストで確認する
- [ ] 4.5 `README.md` に NDLOCR-Lite の取得手順（`git submodule update --init --depth 1`・`git clone --recurse-submodules --shallow-submodules`）・既定エンジンの変更と GLM-OCR への戻し方・前処理をかけない理由・低信頼度の警告の意味・版を上げるときの確認手順・CC BY 4.0 と DINOv3 ライセンスの出典表示を書き、`CLAUDE.md` の技術スタックと `config.toml` のコメントを NDLOCR-Lite 既定に合わせる。書いたコマンドがそのまま動くことを確認する

## 5. 環境確認（`scripts/setup_check.py`）

- [ ] 5.1 必須項目を選ばれたエンジンから組み立てるようにする（design D7: NDLOCR-Lite はソースとモデルの有無・import・版の表示でモデルは読み込まない、選ばれていないエンジンは導入有無の表示だけ、`REQUIRED_PACKAGES` に足した依存を加える）。仕様の 4 Scenario（揃っている・Ollama に接続できない・既定のエンジンが未導入・GLM-OCR を選んでいるときは NDLOCR-Lite を求めない）を `tests/test_setup_check.py` で確認し、`uv run prewar check` を実機で実行して NDLOCR-Lite の版 1.3.1 が表示されることを確かめる

## 6. 統合の確認

- [ ] 6.1 NDLOCR-Lite も Ollama も無い状態を前提にしたテストを含め、`uv run pytest tests/ pkg/` が全件通ることを確認する（仕様「NDLOCR-Lite が無くてもテストが通る」）
- [ ] 6.2 `input/1.png`〜`10.png` をフォルダ指定で 1 記録として処理し（試験用の `--library-root`）、所要時間・失敗数・題名（8 枚目の見出しが行頭に来るか）・列の連結（2 枚目の分かれた列がつながるか）・低信頼度の警告・`meta.json` の `engine_version` を確認し、本文がソースの CLI（公式の固定版）の出力と一致することも確かめて、結果を `survey/ndlocr-lite-survey.md` に追記する
- [ ] 6.3 `--model glm-ocr` で同じ 10 枚を処理し、GLM-OCR の経路（前処理・反復の切り落とし・上限の警告）が従来どおり動くことを確認する
- [ ] 6.4 `PROGRESS.md` の「直近の作業」と `plan/improvement-ideas.md`（A2 の追記）を更新する

## Workflow follow-up

- 実装とレビューが終わったら `/opsx:archive` で仕様（`ocr-engine` 新規・`ocr-pipeline`・`cli`）を本体に統合する
