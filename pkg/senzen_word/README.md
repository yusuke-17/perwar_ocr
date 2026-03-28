# senzen-word

戦前日本語の旧字体・歴史的仮名遣い・カタカナ助詞・変体仮名を現代日本語に変換するPythonライブラリ。

## インストール

```bash
pip install senzen-word
```

## 使い方

```python
import senzen_word

# 全変換を一括適用
result = senzen_word.convert("國會ニ於テ")
# → "国会にて"

# モジュール別
from senzen_word.kanji import convert_old_kanji
from senzen_word.kana import convert_historical_kana, convert_katakana_particles
from senzen_word.kana import convert_hentaigana

# 変換箇所の検出
findings = senzen_word.find("國會ニ於テ")
```

## 変換レイヤー

| レイヤー | 内容 | データ件数 |
|----------|------|-----------|
| 旧字体→新字体 | 常用漢字・人名用漢字・異体字 | 318字 |
| 歴史的仮名遣い→現代仮名遣い | 文化庁「現代仮名遣い」準拠 | 109パターン |
| カタカナ助詞→ひらがな | 複合助詞・単一助詞 | 16パターン |
| 変体仮名→現代ひらがな | Unicode 10.0 変体仮名ブロック | 260字 |

## ライセンス

MIT
