## 1. 変換表への旧字・俗字の追加（`pkg/senzen_word`）

- [x] 1.1 `kanji/data/glyph_old_new.json`（字形違いの旧字 34 字）と `kanji/data/zokuji.json`（俗字 8 字）を作り、`converter.py` の読み込み順を design D2 のとおり `joyo_old_new` → `glyph_old_new` → `zokuji` → `jinmei` → `variants` にする。モジュールの docstring のデータソースにも 2 ファイルを書き足す。`uv run python -c "import senzen_word; print(senzen_word.convert('敎育ニ關スル勅語'))"` が「教育に関スル勅語」を出すことを確認する
- [x] 1.2 `tests/test_kanji.py` に、追加した 42 字すべての変換（パラメータ化）、`嵜` `碕` が変わらないこと、仕様「字形違いの旧字の変換」「俗字の変換」「人名・地名用の異体字の保持」の各 Scenario（`senzen_word.convert` で確かめる）を足す。あわせて design D5 の整合性テスト（5 つの JSON でキーが重複しない・変換先がどの表のキーでもない・`convert_old_kanji` を 2 回かけても変わらない・新字体だけの文が変わらない）を足し、`uv run pytest pkg/senzen_word` が通ることを確認する
- [x] 1.3 `pkg/senzen_word/README.md` の変換レイヤーの表を「常用漢字 372 字・字形違いの旧字 34 字・俗字 8 字・人名用漢字 9 字・異体字 3 字（計 426 字）」に直し（2.3 の判断で 107 字を足し、最終は計 533 字。README とテストも 533 字に更新済み）、版を `pyproject.toml` と `__init__.py` の両方で 0.3.0 に上げる。`get_kanji_table()` の件数が 426 になることをテストで確認する

## 2. 「変換しない字」の一覧と監査ツール（`pkg/senzen_word/tools`）

- [x] 2.1 `tools/audit_kanji_table.py` を design D4 のとおり標準ライブラリだけで実装する（`--charset` 必須、`--unihan` 省略時は Unicode 18.0.0 の Unihan.zip を `tools/.cache/` に取得して再利用、未判断の字を結び付く常用・人名用漢字と簡体字の目安つきで表示、未判断があれば終了コード 1）。`.gitignore` に `pkg/senzen_word/tools/.cache/` を足す。`--unihan` に調査で取得済みの Unihan.zip を渡して実行し、`kanji_keep.json` が空の状態で未判断が 257 字と出て終了コードが 1 になることを確認する
- [x] 2.2 `tools/kanji_keep.json` を作り、まず `嵜` `碕` を `人名地名` として入れる。`tests/test_kanji.py` に、一覧のキーが変換表に無いこと・`reason` が design D3 の 5 種のどれかであること・`note` が空でないことのテストを足し、通ることを確認する
- [x] 2.3 監査が出す残りの未判断の字を 1 字ずつ判断し、変換すべき字が見つかれば 1.1 の表（と 1.2 のテスト・1.3 の件数）に足し、それ以外は理由と根拠を添えて `kanji_keep.json` に入れる。判断に迷う字は `保留` にして note に理由を書く。監査が「未判断 0」で終了コード 0 になること、2.2 のテストが通ることを確認する
- [x] 2.4 `pkg/senzen_word/README.md` の「開発」に監査ツールの使い方（プロジェクトでの実行例 `uv run python pkg/senzen_word/tools/audit_kanji_table.py --charset vendor/ndlocr-lite/src/config/NDLmoji.yaml`、実行する時機（OCR エンジンの更新時・変換表の変更時）、Unihan が結び付けない旧字は拾えない網であること、`kanji_keep.json` の reason の 5 種）を書く。書いたコマンドがそのまま動くことを確認する

## 3. パイプラインと検索への反映（`utils/`・`tests/`）

- [x] 3.1 `utils/library_search.py` の `INDEX_SCHEMA_VERSION` を 3 に上げる。版が 2 であることを確かめていた `tests/test_text_normalizer.py::test_index_schema_version_is_not_raised` と `tests/test_library_search.py::test_schema_version_unchanged_by_query_expression_change` を 3 に更新し、docstring に「G10 で 3 に上げた」と書き足す（design D6）
- [x] 3.2 `tests/test_text_normalizer.py` に、`normalize_text` で「敎育ニ關スル勅語」「內務省」「長嵜縣」がそれぞれ「教育に関スル勅語」「内務省」「長嵜県」になるテストを足す
- [x] 3.3 `tests/test_library_search.py` に、仕様 library-search の 2 つの追加 Scenario を足す: 原文（`ocr_raw.txt`）に「敎育勅語」「內務省」とある記録が「教育勅語」「内務省」で見つかること、版 2 の索引が残っている状態で検索すると作り直されてその記録が見つかること。`uv run pytest tests/ pkg/` が全件通ることを確認する

## 4. 統合確認

- [x] 4.1 `uv run pytest tests/ pkg/` が全件通り、監査ツールが未判断 0 で終わることを確認する。手元の `library/` があれば `uv run prewar search 教育` を実行し、索引の再構築メッセージが 1 回だけ出ることを確認する

## Workflow follow-up

- `plan/improvement-ideas.md` の G10 を対応済みにし、方針の変更（機械生成ではなく判断一覧＋監査）とアーカイブのパスを書く
- `PROGRESS.md` の「次にやる候補」とテスト件数を更新し、`survey/senzen-word-gap-survey.md` の 1 章に対応済みの印を付ける
- 変更をアーカイブし、差分仕様を `openspec/specs/` に統合する
