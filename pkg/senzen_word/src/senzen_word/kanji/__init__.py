"""
漢字変換モジュール

旧字体→新字体、異体字の正規化を行う。
"""

from senzen_word.kanji.converter import convert_old_kanji, find_old_kanji, get_kanji_table

__all__ = ["convert_old_kanji", "find_old_kanji", "get_kanji_table"]
