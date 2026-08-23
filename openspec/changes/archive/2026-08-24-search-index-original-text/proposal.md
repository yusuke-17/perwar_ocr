## Why

FTS5 インデックスに入るのは `modern.txt`（qwen3.5 が口語化した後の文）だけで、
OCR原文の語は一切索引されていない（`utils/library_search.py:304-307`）。
LLM が「罹災者」を「被災者」に、「布達」を「通知」に言い換えれば、**原文にあった語では
永久にヒットしない**。史料アーカイブとして再現率（recall）を損なう欠陥であり、
検索してゼロ件だった利用者は「資料が無い」と誤認する（静かに壊れるタイプ）。

あわせて、差分更新の変更検知が `meta.json` の mtime だけを見ているため
（`utils/library_search.py:108-133`）、`modern.txt` を手で直しても再索引されない。
原文も索引入力に加えると `ocr_raw.txt` も検知漏れの対象に増えるため、同時に直す。

## What Changes

- FTS5 の `search` テーブルに **`original` カラムを追加**し、`normalize_text(ocr_raw.txt)`
  の結果を索引する。旧字体・変体仮名・歴史的仮名遣いを現代表記に揃えた「正規化済み原文」で、
  クエリ側の `normalize_query()` と字体が噛み合う
- 正規化済み原文は**索引時に `normalize_text()` を再実行して得る**。新規ファイルは作らない
  （`scripts/diff_viewer.py:210-211` と同じ手法。決定的・外部依存なし・既存文書に遡って効く）
- 検索は追加設定なしで modern と原文の**両方**を対象にする（FTS5 は列指定のない
  MATCH を全列検索するため、既定の挙動として得られる）
- スニペットを `snippet(search, -1, ...)` に変更し、**実際に一致したカラムから抜粋**する。
  原文だけに残る語で当たったとき、その箇所が見える
- 検索結果に**どのカラムが一致したか**（`modern` / `original` / `title`）を持たせ、
  「原文のみ一致」＝口語化で消えた語であることを表示・JSON出力に出す
- FTS `title` カラムにも `normalize_text()` を適用する。現状 title は生OCR由来のため、
  正規化済みクエリが題名に当たらない同種の取りこぼしがある
- **差分更新の変更検知を `meta.json` / `modern.txt` / `ocr_raw.txt` の3ファイル**に拡張する（G6）
- **BREAKING（内部形式）**: 索引スキーマが変わるため既存の `library/.index/search.db` は
  互換性がない。`PRAGMA user_version` でスキーマ版を持ち、不一致なら自動で作り直す。
  利用者の操作は不要（初回の `search` / `index` / `stat` が黙って再構築し、その旨を表示する）

### Non-goals

- OR/NOT検索・ファセット（C2）、スニペットの色付け・長さ可変（C3）— 別案件
- セマンティック検索（F2）— 別軸
- 正規化前の生OCRテキストそのものの索引 — クエリ側と字体が噛み合わず、
  ノイズを増やすだけなので採らない

## Capabilities

### New Capabilities
- `library-search`: ライブラリ全文検索（索引対象・差分更新・クエリ・検索結果の提示）。
  本変更で初めて仕様化する既存機能であり、今回変更する範囲を仕様として起こす

### Modified Capabilities
（なし。`openspec/specs/` はまだ空で、既存の仕様ファイルは無い）

## Impact

- `utils/library_search.py` — FTS スキーマ、`_insert_doc`、`update()` の変更検知、
  `search()` のスニペットと一致カラム、`SearchHit` dataclass、スキーマ版の移行処理
- `scripts/library.py` — `cmd_find` の結果表示（一致カラムの提示）、`_hit_to_dict` の JSON 出力
- `utils/text_normalizer.py` — 変更なし（`normalize_text` を呼ぶ側が増えるのみ）
- `library/.index/search.db` — 形式変更。初回アクセス時に自動再構築（資料本体には触れない）
- テスト — `tests/test_library_search.py`（新規）。現状 `library_search.py` にテストが無いため、
  索引・差分更新・検索の回帰テストを本変更で用意する
- 外部通信なし・新規依存なし（`sqlite3` と既存の `normalize_text` のみ）
