## 1. ページの結合と目印の部品（`utils/page_join.py`）

- [x] 1.1 `PageEntry` と `join_pages(entries)` を実装する（design D1・D2: 各ページの先頭と末尾の改行・空白だけを除く、末尾が「。」「．」「！」「？」「」」「』」なら `"\n\n"`・それ以外は `"\n"`、本文が空のページは何も足さない）。`tests/test_page_join.py` で、仕様「複数ページの本文の結合」の 4 Scenario（文の途中・句点で終わる・末尾がページ番号「一二」・1 枚）と、「）」で終わるページが改行 1 つになること、空のページで区切りが増えないことを確認する
- [x] 1.2 `gap_marker`・`is_gap_marker`・`split_by_gap_markers` と、`join_pages` の目印の差し込みを実装する（design D3: 失敗は 1 ページ 1 行、未処理は連続した範囲を 1 行にまとめる、目印の前後に空行・本文の先頭と末尾には足さない）。仕様「読み取れなかったページの目印」の 4 Scenario（途中・最初・連続失敗で打ち切り・全ページ成功）を `join_pages` の段階で確認する。あわせて、未処理が 1 ページのときにファイル名つきになること、ファイル名に「〕」や仮名が入っても `is_gap_marker` が判定できること、目印に似ているが行全体が一致しない行（`〔第2頁〕` や本文の途中の〔〕）を目印と判定しないこと、`split_by_gap_markers` で分けた部分を `"\n\n"` でつなぐと元に戻ることも確認する

## 2. 記録を作る段階での結合（`scripts/ocr_vision_llm.py`・`utils/library_writer.py`）

- [x] 2.1 `process_batch` の `"\n\n".join(...)` を、`outcome` から全ページ分の `PageEntry`（成功・失敗・未処理）を作って `join_pages` に渡す形に置き換える。`tests/test_ocr_pipeline.py` で、句点の無い `FakeClient` の 3 枚が改行 1 つでつながること、2 枚目の失敗で目印の行が入ること（仕様「失敗ページのスキップと記録」の改めた Scenario）、連続失敗の打ち切りで未処理の目印が本文の最後に入ること、1 枚の処理の `ocr_raw.txt` が変わらないことを確認する。`"\n\n"` を前提にしていた既存のテスト（3 枚の結合・中間ページの失敗・12 枚のフォルダ）は新しい規則に合わせて直す
- [x] 2.2 `extract_title` で目印の行を飛ばす。1 枚目が失敗した 3 枚の記録で、`meta.json` の題名が 2 枚目の見出しになること（仕様の Scenario「最初のページが失敗する」）と、目印しか無い本文では題名が空になることをテストで確認する
- [x] 2.3 `README.md` の「途中で失敗・中断したとき」に目印の行（形式・入る位置・`ocr_raw.txt` と `modern.txt` の両方に残ること・「読み取り失敗」で全文検索すると失敗のある記録が見つかること）を、「複数画像のページ順」にページのつなぎ方（文の途中なら改行 1 つ、文末なら空行）を書く。書いた形式が 1.2 のテストの出力と一致することを確認する

## 3. 正規化で目印を守る（`utils/text_normalizer.py`）

- [x] 3.1 `normalize_text` の本文を `split_by_gap_markers` で区切り、本文の区間ごとに今までの処理をかけて、目印は触らずにつなぎ直す（design D4）。`tests/test_text_normalizer.py` で、仕様の Scenario「目印のファイル名に仮名や旧字体が含まれる」（`〔第2頁 読み取り失敗（舊記ヰ号.png）〕` が一字も変わらず、前後の旧字体は新字体になる）を確認する。あわせて、`normalize_text(a + 目印 + b)` が `normalize_text(a)`・目印・`normalize_text(b)` を `"\n\n"` でつないだものと一致すること、目印を含まない入力の結果が変わらないこと（既存の正規化のテストが無修正で通る）、`INDEX_SCHEMA_VERSION` が 2 のままであることを確認する
- [x] 3.2 仕様の Scenario「検索と差分表示でも目印が保たれる」を、`tests/test_library_search.py`（目印を含む `ocr_raw.txt` の記録を索引に入れ、原文の列に目印が残ること）と `tests/test_diff_viewer.py`（正規化後の段階に目印が同じ形で出ること）で確認する

## 4. 口語化で目印を守り、字を足さない（`utils/text_modernizer.py`）

- [x] 4.1 `_split_text` の `split("。")` と「。」の付け足しを `_split_keep_delims(text, ("。",))` に置き換える（design D6）。`tests/test_text_modernizer.py` で、仕様の Scenario「句点で終わらない長文」と、どの入力でもチャンクを `"".join` すると元の文と一致することを確認する。`.replace("。", "")` で付け足しを許していた既存のテストは、完全一致で確かめる形に直す
- [x] 4.2 `modernize_detailed` で本文を目印で区切り、区間ごとにチャンクに分けて、目印は LLM に渡さずに組み立て直す（design D5）。`_modernize_chunk` と `_check_model_available` を差し替えた手書きのテスト用の子クラスで、仕様「目印の行を変換しない」の 3 Scenario（途中に目印がある・`prewar fix` 相当の入力・目印だけの文章では LLM を呼ばない）を確認する。あわせて、`chunk_total` が LLM に渡したチャンクの数になること、目印の後ろの区間のチャンクが失敗すると失敗番号が正しく、その区間が原文のまま残ること、仕様の Scenario「変換に失敗した断片が原文のまま残る」も確認する
- [x] 4.3 `SYSTEM_PROMPT` の【制約】に改行の扱いの 1 行を足す案を試し、5.2 の比較で副作用の兆し（見出しの溶け込み・段落の減少）があったため外した（design D7。仕様の要件も削除）。`git diff main -- utils/text_modernizer.py` で `SYSTEM_PROMPT` が変更前と同じであることを確認する

## 5. 全体の確認

- [x] 5.1 `uv run pytest tests/ pkg/` が全件通ることを確認する（Ollama と NDLOCR-Lite が無くても通ること）
- [x] 5.2 `input/1.png`〜`10.png` をフォルダ指定で 1 件の記録として処理し（試験用の `--library-root`）、ページの境目のうちいくつが改行 1 つ・空行になったか、改行 1 つの境目で口語化の結果が 1 つの文として訳されているか、ページ番号や柱が口語化の結果に混ざっていないかを確認する。変更前のブランチで作った同じ 10 枚の記録の `modern.txt` と見比べ、プロンプトの追記で口語化が悪くなっていないことも確認する
- [x] 5.3 2 枚目を壊れた画像（中身が空の `.png`）に差し替えた 3 枚の試験用フォルダを処理し、`ocr_raw.txt`・`modern.txt` に目印の行が入り、1 枚目の末尾と 3 枚目の先頭が 1 つの文として訳されていないこと、題名、終了コード 2 を確認する。`prewar index` のあと `prewar search 読み取り失敗` で、その記録が見つかることも確認する
- [x] 5.4 `PROGRESS.md` の「直近の作業」と、`plan/improvement-ideas.md` の B3・G11 を実装済みに更新する

## Workflow follow-up

- レビューを受けてコミットし、PR で `main` にマージする
- `/opsx:archive` で `ocr-pipeline` の変更と `text-modernization` の新規作成を本体の仕様に統合する
