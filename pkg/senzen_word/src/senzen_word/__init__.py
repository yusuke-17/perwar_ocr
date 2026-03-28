"""
senzen_word — 戦前日本語を現代日本語に変換するライブラリ

戦前の日本語公文書で使われている旧字体・歴史的仮名遣い・
カタカナ助詞・変体仮名を現代日本語に変換する。

使い方:
    import senzen_word

    # 全変換を一括適用
    result = senzen_word.convert("國會ニ於テ")

    # 変換箇所の検出
    findings = senzen_word.find("國會ニ於テ")

    # モジュール別の変換
    from senzen_word.kanji import convert_old_kanji
    from senzen_word.kana import convert_historical_kana, convert_katakana_particles
    from senzen_word.kana import convert_hentaigana
"""

from senzen_word.kanji import convert_old_kanji, find_old_kanji
from senzen_word.kana import (
    convert_historical_kana,
    find_historical_kana,
    convert_katakana_particles,
    find_katakana_particles,
    convert_hentaigana,
    find_hentaigana,
)

__version__ = "0.1.0"

__all__ = ["convert", "find", "__version__"]


def convert(text: str) -> str:
    """
    戦前日本語テキストを現代日本語に一括変換する

    適用順序:
      1. 旧字体 → 新字体
      2. 変体仮名 → 現代ひらがな
      3. 歴史的仮名遣い → 現代仮名遣い
      4. カタカナ助詞 → ひらがな

    Args:
        text: 変換対象のテキスト

    Returns:
        現代日本語に変換されたテキスト
    """
    # ① 漢字（旧字体→新字体）
    text = convert_old_kanji(text)
    # ② 変体仮名→現代ひらがな
    text = convert_hentaigana(text)
    # ③ 歴史的仮名遣い→現代仮名遣い
    text = convert_historical_kana(text)
    # ④ カタカナ助詞→ひらがな
    text = convert_katakana_particles(text)
    return text


def find(text: str) -> list[tuple[str, str, int, str]]:
    """
    テキスト中の変換対象箇所を検出する

    Args:
        text: 検査対象のテキスト

    Returns:
        (変換前, 変換後, 出現位置, カテゴリ) のリスト
        カテゴリ: "kanji", "hentaigana", "kana", "particle"
    """
    found: list[tuple[str, str, int, str]] = []

    for old, new, pos in find_old_kanji(text):
        found.append((old, new, pos, "kanji"))

    for old, new, pos in find_hentaigana(text):
        found.append((old, new, pos, "hentaigana"))

    for old, new, pos in find_historical_kana(text):
        found.append((old, new, pos, "kana"))

    for old, new, pos in find_katakana_particles(text):
        found.append((old, new, pos, "particle"))

    # 位置順にソート
    found.sort(key=lambda x: x[2])
    return found
