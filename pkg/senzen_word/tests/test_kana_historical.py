"""歴史的仮名遣い変換のテスト"""

from senzen_word.kana.historical import convert_historical_kana, find_historical_kana


class TestConvertHistoricalKana:
    """convert_historical_kana のテスト"""

    def test_wi_we(self):
        """ゐ→い、ゑ→え の基本変換"""
        assert convert_historical_kana("ゐ") == "い"
        assert convert_historical_kana("ゑ") == "え"
        assert convert_historical_kana("ヰ") == "イ"
        assert convert_historical_kana("ヱ") == "エ"

    def test_gouon(self):
        """合拗音: くゎ→か、グヮ→ガ"""
        assert convert_historical_kana("くゎし") == "かし"
        assert convert_historical_kana("グヮイ") == "ガイ"

    def test_tefu(self):
        """てふ→ちょう"""
        assert convert_historical_kana("てふてふ") == "ちょうちょう"
        assert convert_historical_kana("テフテフ") == "チョーチョー"

    def test_katakana_long_vowel_au(self):
        """カタカナ〜アウ→〜オー"""
        assert convert_historical_kana("カウ") == "コー"
        assert convert_historical_kana("サウ") == "ソー"
        assert convert_historical_kana("タウ") == "トー"

    def test_katakana_long_vowel_eu(self):
        """カタカナ〜エウ→〜ヨー系"""
        assert convert_historical_kana("セウ") == "ショー"
        assert convert_historical_kana("テウ") == "チョー"

    def test_katakana_long_vowel_iu(self):
        """カタカナ〜イウ→〜ユー系"""
        assert convert_historical_kana("キウ") == "キュー"
        assert convert_historical_kana("シウ") == "シュー"

    def test_hiragana_au(self):
        """ひらがな〜あう→〜おう"""
        assert convert_historical_kana("かう") == "こう"
        assert convert_historical_kana("さう") == "そう"
        assert convert_historical_kana("やう") == "よう"

    def test_hiragana_eu(self):
        """ひらがな〜えう→〜ょう"""
        assert convert_historical_kana("せう") == "しょう"
        assert convert_historical_kana("てう") == "ちょう"

    def test_hiragana_iu(self):
        """ひらがな〜いう→〜ゅう（文化庁付表追加分）"""
        assert convert_historical_kana("いう") == "ゆう"
        assert convert_historical_kana("きう") == "きゅう"
        assert convert_historical_kana("しう") == "しゅう"

    def test_hiragana_new_additions(self):
        """文化庁付表で追加した不足分"""
        assert convert_historical_kana("なう") == "のう"
        assert convert_historical_kana("わう") == "おう"
        assert convert_historical_kana("ねう") == "にょう"
        assert convert_historical_kana("めう") == "みょう"
        assert convert_historical_kana("れう") == "りょう"
        assert convert_historical_kana("でう") == "ぢょう"

    def test_wo_not_converted(self):
        """ヲ は助詞として残す（変換しない）"""
        assert convert_historical_kana("命令ヲ受ケタ") == "命令ヲ受ケタ"

    def test_no_change_for_modern(self):
        """現代仮名遣いのテキストは変化しない"""
        text = "現代の日本語テキスト"
        assert convert_historical_kana(text) == text

    def test_empty_string(self):
        assert convert_historical_kana("") == ""

    def test_mixed_text(self):
        """漢字混じりの文でも仮名部分のみ変換"""
        text = "さうだ、京都へ行かう"
        expected = "そうだ、京都へ行こう"
        assert convert_historical_kana(text) == expected


class TestFindHistoricalKana:
    """find_historical_kana のテスト"""

    def test_find_basic(self):
        found = find_historical_kana("ゐ")
        assert len(found) == 1
        assert found[0] == ("ゐ", "い", 0)

    def test_find_multiple(self):
        found = find_historical_kana("ゐとゑ")
        assert len(found) == 2

    def test_find_empty(self):
        found = find_historical_kana("現代語")
        assert len(found) == 0
