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
| 旧字体→新字体 | 常用漢字 372字・人名用漢字 9字・異体字 3字 | 384字 |
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

## ライセンス

MIT
