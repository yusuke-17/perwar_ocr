"""変体仮名変換のテスト"""

from senzen_word.kana.hentaigana import convert_hentaigana, find_hentaigana


class TestConvertHentaigana:
    """convert_hentaigana のテスト"""

    def test_basic_conversion(self):
        """基本的な変体仮名→ひらがな変換"""
        # U+1B002 = HENTAIGANA LETTER A-I → い
        result = convert_hentaigana("\U0001B002")
        assert result == "い"

    def test_multiple_variants(self):
        """同じ音の複数の変体仮名が正しく変換される"""
        # U+1B002, U+1B003, U+1B004 はすべて「い」の変体仮名
        text = "\U0001B002\U0001B003\U0001B004"
        result = convert_hentaigana(text)
        assert result == "いいい"

    def test_no_change_for_modern(self):
        """現代ひらがなは変化しない"""
        text = "あいうえお"
        assert convert_hentaigana(text) == text

    def test_mixed_text(self):
        """変体仮名と通常テキストの混在"""
        text = "漢字\U0001B002テスト"
        result = convert_hentaigana(text)
        assert result == "漢字いテスト"

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
        assert found[0][1] == "い"
        assert found[0][2] == 0

    def test_find_empty(self):
        found = find_hentaigana("現代語")
        assert len(found) == 0
