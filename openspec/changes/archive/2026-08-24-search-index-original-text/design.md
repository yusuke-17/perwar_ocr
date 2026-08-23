## Context

動機は proposal.md - Why を参照。設計に効く現状は以下の3点。

1. **正規化後テキストはどこにも保存されていない。** ライブラリに残るのは `ocr_raw.txt`（生OCR）と
   `modern.txt`（口語化後）だけ。`scripts/diff_viewer.py:210-211` は正規化後テキストを
   「`normalize_text(ocr_raw)` を再実行して再現する（決定的・高速・外部依存なし）」方式で扱っており、
   本変更もこの既存パターンに乗る。
2. **`normalize_query()` は `normalize_text()` の照合サブセットとして設計済み**
   （`utils/text_normalizer.py:201-230`）。索引側の変換列とクエリ側の変換列を揃える契約が
   すでにコメントで明文化されている。「索引側だけに変換を足すとその文字を含むクエリが
   永久にヒットしなくなる」— 今回追加する原文カラムも同じ `normalize_text()` を通すことで、
   modern カラムと同じ土俵に乗る。
3. **`library_search.py` にテストが1件も無い。** FTS スキーマと差分更新ロジックを同時に触るため、
   回帰テストの新設を本変更に含める。

制約: 完全ローカル（sqlite3 と既存 `normalize_text` のみ、新規依存なし）。
SQLite は 3.50.4（trigram tokenizer / `snippet(tbl, -1, ...)` / `highlight()` いずれも利用可）。

## Goals / Non-Goals

**Goals:**

- 索引の入力を「口語化後テキストのみ」から「口語化後テキスト＋正規化済み原文＋正規化済み題名」へ広げる
- 検索結果から「なぜ当たったか」（どのカラムが一致したか）を判別可能にする
- 差分更新の変更検知を、索引入力となる全ファイルに対して正しくする
- 既存の `search.db` を利用者の手を煩わせずに移行する
- `library_search.py` に回帰テストの土台を作る

**Non-Goals:**

- 検索構文の拡張（カラム指定検索 `original:～` を CLI に公開する等）。FTS5 の内部機能としては
  使えるが、UI として出すのは C2 の範囲
- ランキングのチューニング（`bm25` のカラム重み付け）。既定のまま出し、実データを見てから判断する
- 正規化後テキストのファイル保存（`normalized.txt`）。再実行方式で足りる

## Decisions

### D1. 正規化済み原文は索引時に `normalize_text(ocr_raw.txt)` を再計算する

**採用理由**: `normalize_text()` は純Pythonの決定的変換で、外部依存も乱数もない。
既存文書に遡って効き、ライブラリのファイル構成・`meta.json` スキーマを一切変えずに済む。
`diff_viewer.py` がすでに同じ方式を採っており、パターンが揃う。

**代替案**:
- *OCR時に `normalized.txt` を保存*: 索引は軽くなるが、`library_writer` と `meta.json` の
  スキーマ変更が要り、既存文書には無いファイルなので結局「無ければ再計算」の分岐が残る。
  2経路を抱える分だけ悪い。
- *生 `ocr_raw` をそのまま索引*: 実装は最小だが、旧字体「關」・変体仮名・歴史的仮名遣いが
  正規化済みクエリと噛み合わず、狙った再現率が出ない。目的を達しないので却下。

**副作用**: 将来 `normalize_text()` の変換規則を変えたら、索引済みの原文は古い規則のまま残る。
D5 のスキーマ版を上げれば全件再構築で追従できる（変換規則を変えたら版を上げる、という運用にする）。

### D2. FTS5 テーブルに `original` カラムを追加し、`title` にも正規化を適用する

```sql
CREATE VIRTUAL TABLE search USING fts5(
    id UNINDEXED,
    title,       -- normalize_text(meta.title) …照合用。表示は documents.title（生のまま）
    modern,      -- modern.txt（従来どおり）
    original,    -- normalize_text(ocr_raw.txt) …今回追加
    tokenize = 'trigram'
);
```

カラム指定のない `MATCH` は FTS5 が全カラムを対象にするため、検索クエリ生成
（`_build_match_expr`）は変更不要で、そのまま原文も検索対象になる。

`title` の正規化は「索引は照合用、表示は生」の分離による。表示用の題名は
`documents.title` に生のまま保持し、そちらを `SearchHit.title` に載せる（現行どおり）。

`ocr_raw.txt` が読めない場合は `original` を空文字で挿入し、文書自体は索引する。
現状 `modern.txt` が読めないと文書ごとスキップされる挙動は維持する（本文が無いなら索引する意味がない）。

### D3. スニペットは `snippet(search, -1, ...)`、一致カラムは `highlight()` のマーカ有無で判定する

`snippet(tbl, -1, ...)` は「最もよく一致したカラム」から抜粋を返す。実挙動を確認済み:

| クエリの当たり方 | `snippet(t, -1, ...)` の出所 |
|---|---|
| 原文のみ一致 | 原文（一致箇所を強調） |
| modern のみ一致 | modern |
| 両方一致 | よりよく一致した方 |

一致カラムの判定は `instr(highlight(search, N, char(2), char(3)), char(2)) > 0` を
title / modern / original の3カラム分 SELECT に並べる。`highlight()` は一致が無ければ
マーカを入れずにカラム全文を返すので、マーカの有無がそのまま一致フラグになる。

**代替案**: カラムごとに MATCH を投げ直す（クエリ3倍）、`fts5vocab` を引く（複雑）。
どちらも `highlight()` 一発より重く、得るものが無い。

**コスト**: `highlight()` は該当カラム全文を組み立てて返すため、結果1件あたり本文数KBの
文字列を3本生成する。`LIMIT` は既定20件なので実用上は無視できる。区切り文字に
`char(2)`/`char(3)`（制御文字 STX/ETX）を使うのは、本文に出現しないことを保証するため。

**データ表現**: `SearchHit` に `matched_fields: tuple[str, ...]` を追加する
（`("modern",)`, `("original",)`, `("title", "modern")` など）。
`scripts/library.py:161-171` のテキスト表示では、`original` を含み `modern` を含まない場合のみ
`（原文のみ一致：口語化で語が変わっています）` を付す。JSON 出力は `_hit_to_dict` が
`asdict` を使っているので `matched_fields` は自動的に載る（tuple → list 変換のみ確認する）。

### D4. 差分更新の判定を「索引入力3ファイルの mtime 署名」にする（G6）

`documents` テーブルに `source_sig TEXT NOT NULL` を追加し、

```
source_sig = "meta:{mtime}|modern:{mtime}|raw:{mtime}"   # mtime は f"{st_mtime:.6f}"、欠損は "-"
```

の**文字列一致**で変更を判定する。既存の `mtime REAL`（`meta.json` の mtime）は
`stat()` の「最終更新」表示が使っているので残す。

**代替案**:
- *3ファイルの最大 mtime を比較*: カラムを増やさずに済むが、ファイルを古い版に戻したとき
  最大値が下がらず検知漏れが起きる。文字列一致ならどちらへ動いても検知する。
- *内容ハッシュ*: 最も確実だが全ファイルを毎回読む必要がある。mtime なら `stat()` だけで済み、
  ハッシュが要る局面（mtime を保たないコピー等）は本PJの想定外。

### D5. スキーマ版を `PRAGMA user_version` に持ち、不一致なら自動で作り直す

`INDEX_SCHEMA_VERSION = 2`。`_ensure_schema(conn) -> bool` を「移行が起きたか」を返す形に変え、

- テーブルが存在しない → 新規作成し版を刻む（`migrated = False`）
- `user_version` が現行と異なる（旧DBは `0`）→ `documents` / `search` を DROP して作り直し、
  版を刻む（`migrated = True`）

`update()` は移行後 `existing` が空になるので、そのまま全件再索引される（追加の分岐不要）。
`search()` / `stat()` は先頭で `_ensure_ready()` を呼び、移行が起きていたら
`⚠ インデックス形式が変わったため再構築します...` を表示して `update()` を実行してから本処理に入る。
既存の「インデックス未構築なら自動 update」（`scripts/library.py:141-144`）と同じUXに揃える。

**代替案**: FTS5 への `ALTER TABLE ... ADD COLUMN`。SQLite 3.35+ で可能だが、
既存行の `original` は NULL のままで結局全件再索引が要る。`documents` 側のカラム追加も
併せて必要になり、分岐だけ増えて得が無い。

**安全性**: 破棄するのは `library/.index/search.db` の中身だけ。資料（`ocr_raw.txt` /
`modern.txt` / `meta.json` / 画像）には触れず、索引はいつでも再生成できる派生物である。

### D6. `library_search.py` の回帰テストを新設する

`tests/test_library_search.py` を追加し、`tmp_path` に最小のライブラリ構成を組んで
sqlite3 で完結させる（Ollama 不要・外部通信なし）。既存 `tests/` の pytest スタイルに合わせる。

## Risks / Trade-offs

- **[索引サイズがほぼ倍増する]** → trigram は元テキストの数倍のインデックスを作るため、
  原文カラム追加で `search.db` は概ね1.8〜2倍になる。テキストのみで画像は含まないので
  絶対量は小さい。`prewar stat` にサイズ表示があり、増加は利用者から見える。
  **実測（合成200件・原文2.7KB/件）: 1172KB → 1840KB の 1.57倍**。想定より軽く収まった。
- **[ランキングが変わる]** → カラムが増えることで `bm25` のスコアが変動し、既存クエリの
  並び順が変わる。原文と modern の両方に当たる文書が上位に来る方向で、意図と概ね一致する。
  重み付けは実データを見てから（Non-Goals）。
- **[口語化後と原文の重複ヒットでスコアが二重計上される]** → 同じ語が両方にある文書は
  実質2回数えられる。「原文でも現代語でも同じ表現」＝素直な一致なので、上位に来ること自体は妥当。
- **[索引更新が重くなる]** → 全文書で `normalize_text()` を再実行する。純Pythonの辞書変換で
  1文書あたりミリ秒オーダー、かつ差分更新なら変更文書のみ。初回の全件再構築だけが一度重い。
  **実測（同上）: `normalize_text` 0.34ms/件、全件再構築 0.10秒/200件（≒0.5ms/件）、
  変更なしの差分更新 4.7ms/200件、検索 1.9ms**。1000件規模でも再構築は1秒未満で、
  想定どおり無視できるコスト。実測は合成ライブラリによる（ローカルに実データが無いため）。
- **[初回アクセスで黙って全件再構築が走る]** → 文書数が多いと `prewar search` の初回だけ
  待たされる。メッセージを出して理由を明示する（D5）。
- **[`normalize_text()` の変換規則を変えたとき索引が古いまま残る]** → 規則変更時は
  `INDEX_SCHEMA_VERSION` を上げる運用にし、その旨をコード上のコメントで明記する。

## Migration Plan

1. 実装をマージした時点では何も起きない（索引は触られない）
2. 利用者が次に `prewar search` / `prewar index` / `prewar stat` を実行した時、
   `PRAGMA user_version` の不一致を検出して索引を自動で作り直す
3. 手動操作は不要。明示的にやり直したい場合は従来どおり `uv run prewar index --rebuild`
4. **ロールバック**: 実装を戻すと `user_version` が再び不一致になり、旧形式で自動再構築される。
   資料本体は一切変更されないため、索引の再生成以外の後始末は不要
