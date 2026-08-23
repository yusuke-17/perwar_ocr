## 1. 回帰テストの土台を先に作る

`library_search.py` には現在テストが1件も無い。スキーマと差分更新を同時に触るため、
**現行挙動を固定するテストを先に書き、それが緑のまま実装に進む**。

- [x] 1.1 `tests/test_library_search.py` を新設し、`tmp_path` に最小ライブラリ
      （`meta.json` + `ocr_raw.txt` + `modern.txt` を持つ文書フォルダ）を組む
      フィクスチャを用意する。`uv run pytest tests/test_library_search.py` が収集できることを確認
- [x] 1.2 現行挙動の回帰テストを書く: `update()` の追加/更新/削除/スキップ件数、
      `modern.txt` の語での検索ヒット、`delete()`、`stat()` の文書数。
      **実装前の状態で全件パスすること**を確認（外部通信・Ollama 不要）

## 2. 索引スキーマと移行（design D2 / D5）

- [x] 2.1 `INDEX_SCHEMA_VERSION = 2` を定数として追加し、`search` テーブルに
      `original` カラムを、`documents` テーブルに `source_sig TEXT NOT NULL` を加えた
      新スキーマを `_ensure_schema` に定義する
- [x] 2.2 `_ensure_schema(conn) -> bool` に変更し、`PRAGMA user_version` で版を判定する:
      テーブル未作成なら新規作成して版を刻み `False`、版が不一致（旧DBは `0`）なら
      `documents` / `search` を DROP して作り直し版を刻み `True` を返す
- [x] 2.3 `_ensure_ready()` を追加し、`search()` / `stat()` の先頭で呼ぶ。移行が起きていたら
      `⚠ インデックス形式が変わったため再構築します...` を表示して `update()` を実行してから本処理へ進む
- [x] 2.4 旧形式DBからの移行テスト: 旧スキーマ（`original` 無し・`user_version` 0）のDBを
      手で作り、`search()` を呼ぶと自動再構築されて正しい結果が返ること、
      **ライブラリ内の資料ファイルが1つも変更されていないこと**（更新前後の mtime 比較）を検証

## 3. 正規化済み原文の索引（design D1 / D2）

- [x] 3.1 `_load_original(doc_dir) -> str` を追加する。`ocr_raw.txt` を読んで
      `normalize_text()` を適用して返す。ファイルが無い/読めない場合は警告を出して
      **空文字を返し、文書自体はスキップしない**（`_load_modern` の「読めなければ None＝スキップ」とは挙動が異なる点をdocstringに明記）
- [x] 3.2 `_insert_doc` を `original` カラム対応にし、FTS の `title` には
      `normalize_text(title)` を入れる。`documents.title` は生のまま保持する
      （表示用と照合用の分離をコメントで明記）
- [x] 3.3 `update()` の追加/更新パスで `_load_original` を呼び、`_insert_doc` に渡す
- [x] 3.4 テスト: 原文にのみ存在する語（例: 旧字体・歴史的仮名遣いを含む語）で検索して
      ヒットすること、`modern.txt` にのみある語でも従来どおりヒットすること、
      `ocr_raw.txt` が無い文書でも `modern.txt` 検索が機能し索引から除外されないこと
- [x] 3.5 テスト: 旧字体の題名（例「關東大震災ノ記錄」）を現代表記（「関東大震災」）で検索してヒットし、
      `SearchHit.title` は生の「關東大震災ノ記錄」のまま返ること
      （当初例に挙げた「內」U+5167 は senzen_word の変換表に無く変換されない。
      本変更の範囲外なので 6.6 で改善案として記録する）
- [x] 3.6 テスト: 同じ原文で `update()` を2回実行しても索引される正規化済み原文が同一であること（決定性）

## 4. 差分更新の変更検知（design D4 / G6）

- [x] 4.1 `_source_sig(doc_dir) -> str` を追加する。`meta.json` / `modern.txt` / `ocr_raw.txt` の
      mtime を `f"{st_mtime:.6f}"`（欠損は `"-"`）で連結した署名文字列を返す
- [x] 4.2 `update()` の変更判定を `mtime` の差分比較から `source_sig` の**文字列一致**に置き換える。
      `documents.mtime`（`meta.json` の mtime）は `stat()` の表示用に引き続き保存する
- [x] 4.3 テスト: `modern.txt` だけを書き換えて `update()` → 再索引され新しい本文で検索でき、
      **古い本文では検索されない**こと（`updated` が1件）
- [x] 4.4 テスト: `ocr_raw.txt` だけを書き換えて `update()` → 再索引され新しい原文の語で検索できること
- [x] 4.5 テスト: どのファイルも変更していない場合 `update()` が再索引せず、
      `added` / `updated` がいずれも 0 であること

## 5. 一致カラムの提示（design D3）

- [x] 5.1 `SearchHit` に `matched_fields: tuple[str, ...]` を追加する（`("original",)` 等）
- [x] 5.2 `search()` の SELECT を更新する: 抜粋を `snippet(search, -1, '[', ']', '...', 16)` に変え、
      title / modern / original の3カラム分
      `instr(highlight(search, N, char(2), char(3)), char(2)) > 0` を並べて `matched_fields` を組む
- [x] 5.3 `scripts/library.py` の `cmd_find` テキスト表示で、`original` を含み `modern` を含まない
      結果に `（原文のみ一致：口語化で語が変わっています）` を付す
- [x] 5.4 `_hit_to_dict` の JSON 出力に `matched_fields` が list として載ることを確認する
      （`asdict` の tuple 変換を検証）
- [x] 5.5 テスト: 原文のみ一致 → 抜粋が原文から出て `matched_fields == ("original",)`、
      modern 一致 → 抜粋が modern から出ること

## 6. 仕上げ・検証

- [x] 6.1 全件再構築の所要時間を実測する（`time uv run prewar index --rebuild`）。
      文書1件あたりの `normalize_text()` コストが想定（ミリ秒オーダー）に収まるか確認し、
      外れていれば design の Risks に実測値を追記して対応を判断する
- [x] 6.2 `search.db` のサイズ変化を実測し（`uv run prewar stat`）、想定の1.8〜2倍程度に
      収まっているか確認する
- [x] 6.3 `uv run pytest tests/ pkg/` が全件パスすることを確認する（既存167件＋本変更の追加分）
- [x] 6.4 実ライブラリで手動確認: 口語化で言い換えられた語を1つ選び、
      変更前はゼロ件・変更後はヒットすることを確かめる
      → **ローカルの `library/` が空のため合成文書で実施**（実データでの確認は未了）。
      原文「罹災者ノ數ハ」／口語化後「被災者の数は」で、`uv run prewar search 罹災者` が
      改修前スキーマ 0件 → 改修後 1件（`← 原文のみ一致` の注記つき）を CLI 経由で確認
- [x] 6.5 `normalize_text()` の変換規則を変えたら `INDEX_SCHEMA_VERSION` を上げる旨を
      `library_search.py` と `text_normalizer.py` の双方にコメントで残す
- [x] 6.6 `plan/improvement-ideas.md` の G5 / G6 を実装済みに更新し、優先順位リストを繰り上げる
- [x] 6.7 `README.md` の検索の説明に「原文の語でも検索できる」旨と一致表示を追記する
