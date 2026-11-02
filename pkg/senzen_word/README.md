# senzen-word

戦前日本語の旧字体・歴史的仮名遣い・カタカナ助詞・変体仮名を現代日本語に変換するPythonライブラリ。
外部依存はゼロ（Python 標準ライブラリのみ）。

## インストール

```bash
pip install senzen-word
```

## 使い方

```python
import senzen_word

# 全変換を一括適用（旧字体 → 変体仮名 → 歴史的仮名遣い → カタカナ助詞 の順）
result = senzen_word.convert("帝國議會ニ於テハ豫算ヲ議決セリ")
# → "帝国議会に於テハ予算を議決セリ"
# ※ 辞書にある字と助詞だけを置き換える。「於テハ」「セリ」のような
#    文語の言い回しは変えない（口語化は範囲外）

# 変換箇所の検出: (変換前, 変換後, 出現位置, カテゴリ) のリスト
findings = senzen_word.find("帝國議會ニ於テハ")
# → [("國", "国", 1, "kanji"), ("會", "会", 3, "kanji"), ("ニ", "に", 4, "particle")]
```

### モジュール別の関数

変換（`convert_*`）と検出（`find_*`）が対になっている。
検出関数は `(変換前, 変換後, 出現位置)` のリストを返す。

```python
from senzen_word.kanji import convert_old_kanji, find_old_kanji, get_kanji_table
from senzen_word.kana import (
    convert_hentaigana, find_hentaigana,
    convert_historical_kana, find_historical_kana,
    convert_katakana_particles, find_katakana_particles,
)

get_kanji_table()  # 旧字体 → 新字体 の対応表（dict）
```

個別の関数を使うと、途中に別の処理（全角正規化など）を挟める。

## 変換レイヤー

| レイヤー | 内容 | データ件数 |
|----------|------|-----------|
| 旧字体→新字体 | 常用漢字 372字・字形違いの旧字 35字・俗字 42字・人名用漢字 9字・異体字 75字 | 533字 |
| 歴史的仮名遣い→現代仮名遣い | 文化庁「現代仮名遣い」準拠 | 92パターン |
| カタカナ助詞→ひらがな | 複合助詞 8・単一助詞 8 | 16パターン |
| 変体仮名→現代ひらがな | Unicode 10.0 変体仮名ブロック | 285字 |

## 開発

リポジトリ直下（uv ワークスペース）で実行する。

```bash
# テスト
uv run pytest pkg/senzen_word

# 変体仮名テーブル（src/senzen_word/kana/data/hentaigana.json）の再生成
# Unicode の正式な文字名から機械的に作る。正しさはテストが同じ規則で再検証する
uv run python pkg/senzen_word/tools/gen_hentaigana.py
```

### 旧字体変換表の監査

旧字体の変換表（`src/senzen_word/kanji/data/`）は、人が1字ずつ判断して作る。
Unicode の異体字データ（Unihan）から自動生成すると、`壹→一`（正しくは 壱）のような誤りが混ざるためである。
監査ツールは、OCR エンジンが出しうる字のうち「旧字の候補なのに、変換表にも『変換しない字』の一覧にも無い字」を洗い出す。

```bash
# プロジェクト（prewar-ocr）での実行例。NDLOCR-Lite の出力文字集合を渡す
uv run python pkg/senzen_word/tools/audit_kanji_table.py \
    --charset vendor/ndlocr-lite/src/config/NDLmoji.yaml
```

- 実行する時機: OCR エンジン（文字集合）を更新したとき、変換表や一覧を変えたとき
- 未判断の字があれば、結び付く常用・人名用漢字と一緒に表示し、終了コード 1 で終わる。0 字なら終了コード 0
- 初回は Unicode 公式サイトから Unihan.zip（版は固定）を取得し、`tools/.cache/` に保存して再利用する。`--unihan <パス>` で手元のファイルも使える
- 見つかった字は、変換する字なら変換表の JSON に、変換しない字なら `tools/kanji_keep.json` に理由（`reason`）と根拠（`note`）を付けて入れる。`reason` は次の5種:
  - `人名地名`: 人名・地名に使われる異体字（`嵜` `碕` など）
  - `簡体字`: 中国の簡体字。OCR の誤読の可能性が高い
  - `別字`: 日本語では別の字・別の語として使う、または Unihan の結び付きが誤り（`儘`＝まま、`吋`＝インチ など）
  - `書きかえ`: 同音の漢字による書きかえ（`慾→欲` など）。字体の違いではない
  - `保留`: 変換先が文脈で決まる、または用例を見て決めたいもの
- 注意: これは判断漏れを減らす網で、完全ではない。Unihan が常用漢字と結び付けない旧字（`尙` `產` など）は監査に出ないので、OCR 結果で見つけたら手で変換表に足し、テストを1行加える

## ライセンス

MIT
