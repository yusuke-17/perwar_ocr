"""変体仮名変換のテスト"""

import json
import unicodedata
from importlib import resources

from senzen_word.kana.hentaigana import convert_hentaigana, find_hentaigana


class TestConvertHentaigana:
    """convert_hentaigana のテスト"""

    def test_basic_conversion(self):
        """基本的な変体仮名→ひらがな変換"""
        # U+1B002 = HENTAIGANA LETTER A-1 → あ
        # （末尾の "-1" は「あ」の1番目の異体字という意味の通し番号。
        #   初版はこれを "A-I"（あい）と誤読して「い」に割り当てており、
        #   テーブル全体がズレる原因になっていた）
        result = convert_hentaigana("\U0001B002")
        assert result == "あ"

    def test_multiple_variants(self):
        """同じ音の複数の変体仮名が正しく変換される"""
        # U+1B002, U+1B003, U+1B004 は A-1 / A-2 / A-3 ＝すべて「あ」の変体仮名
        text = "\U0001B002\U0001B003\U0001B004"
        result = convert_hentaigana(text)
        assert result == "あああ"

    def test_ra_row_converted(self):
        """初版で丸ごと欠落していた「ら行」が変換される（U+1B0ED〜U+1B100）"""
        # RA-1 / RI-1 / RU-1 / RE-1
        text = "\U0001B0ED\U0001B0F1\U0001B0F8\U0001B0FE"
        assert convert_hentaigana(text) == "らりるれ"

    def test_wi_we_wo_n(self):
        """初版で変換先に一度も現れなかった ゐ・ゑ、および を・ん"""
        assert convert_hentaigana("\U0001B10D") == "ゐ"  # WI-1
        assert convert_hentaigana("\U0001B112") == "ゑ"  # WE-1
        assert convert_hentaigana("\U0001B116") == "を"  # WO-1
        assert convert_hentaigana("\U0001B11D") == "ん"  # N-MU-MO-1

    def test_yo1_not_dropped(self):
        """U+1B0E7 (YO-1) が「よ」に変換される

        初版は値が "こと" の2文字だったためローダのフィルタに黙って捨てられ、
        変換されずに残っていた。
        """
        assert convert_hentaigana("\U0001B0E7") == "よ"

    def test_no_change_for_modern(self):
        """現代ひらがなは変化しない"""
        text = "あいうえお"
        assert convert_hentaigana(text) == text

    def test_mixed_text(self):
        """変体仮名と通常テキストの混在"""
        text = "漢字\U0001B002テスト"
        result = convert_hentaigana(text)
        assert result == "漢字あテスト"

    def test_empty_string(self):
        assert convert_hentaigana("") == ""

    def test_type_error(self):
        """str以外の入力でTypeError"""
        import pytest
        with pytest.raises(TypeError):
            convert_hentaigana(123)


class TestFindHentaigana:
    """find_hentaigana のテスト"""

    def test_find_basic(self):
        found = find_hentaigana("\U0001B002")
        assert len(found) == 1
        assert found[0][1] == "あ"
        assert found[0][2] == 0

    def test_find_empty(self):
        found = find_hentaigana("現代語")
        assert len(found) == 0


class TestTableIntegrity:
    """変換テーブル自体の健全性

    データは tools/gen_hentaigana.py が unicodedata から生成する。
    ここでは同じ規則を独立に再実装して突き合わせ、テーブルがズレたら落とす。
    """

    # 字母の音（ローマ字）→ 現代ひらがな
    ROMAJI = {
        "A": "あ", "I": "い", "U": "う", "E": "え", "O": "お",
        "KA": "か", "KI": "き", "KU": "く", "KE": "け", "KO": "こ",
        "SA": "さ", "SI": "し", "SU": "す", "SE": "せ", "SO": "そ",
        "TA": "た", "TI": "ち", "TU": "つ", "TE": "て", "TO": "と",
        "NA": "な", "NI": "に", "NU": "ぬ", "NE": "ね", "NO": "の",
        "HA": "は", "HI": "ひ", "HU": "ふ", "HE": "へ", "HO": "ほ",
        "MA": "ま", "MI": "み", "MU": "む", "ME": "め", "MO": "も",
        "YA": "や", "YU": "ゆ", "YO": "よ",
        "RA": "ら", "RI": "り", "RU": "る", "RE": "れ", "RO": "ろ",
        "WA": "わ", "WI": "ゐ", "WE": "ゑ", "WO": "を",
        "N": "ん",
    }

    @staticmethod
    def _load_json() -> dict[str, str]:
        resource = resources.files("senzen_word.kana") / "data" / "hentaigana.json"
        return json.loads(resource.read_text(encoding="utf-8"))

    def test_table_matches_unicode_names(self):
        """全エントリが Unicode 正式名から導ける読みと一致する"""
        table = self._load_json()

        for char, hiragana in table.items():
            name = unicodedata.name(char)
            assert name.startswith("HENTAIGANA LETTER "), f"U+{ord(char):04X} {name}"
            romaji = name[len("HENTAIGANA LETTER "):].split("-")[0]
            expected = self.ROMAJI[romaji]
            assert hiragana == expected, (
                f"U+{ord(char):04X} {name}: 期待 {expected} / 実際 {hiragana}"
            )

    def test_table_covers_all_hentaigana(self):
        """Unicode 上の変体仮名を1字も取りこぼしていない"""
        table = self._load_json()

        expected_chars = set()
        for codepoint in range(0x1B002, 0x1B11F):
            char = chr(codepoint)
            try:
                name = unicodedata.name(char)
            except ValueError:
                continue
            if name.startswith("HENTAIGANA LETTER "):
                expected_chars.add(char)

        assert set(table) == expected_chars
        assert len(table) == 285

    def test_conversion_leaves_no_hentaigana(self):
        """全変体仮名を通しても BMP 外の文字が残らない"""
        table = self._load_json()
        converted = convert_hentaigana("".join(table))
        assert all(ord(c) <= 0xFFFF for c in converted)
