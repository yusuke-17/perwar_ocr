"""漢字変換のテスト"""

from senzen_word.kanji import convert_old_kanji, find_old_kanji, get_kanji_table


class TestConvertOldKanji:
    """convert_old_kanji のテスト"""

    def test_joyo_basic(self):
        """常用漢字の旧→新変換"""
        assert convert_old_kanji("國會") == "国会"
        assert convert_old_kanji("學問") == "学問"
        assert convert_old_kanji("經濟") == "経済"

    def test_ben_variants(self):
        """「弁」の3旧字体"""
        assert convert_old_kanji("辨") == "弁"
        assert convert_old_kanji("瓣") == "弁"
        assert convert_old_kanji("辯") == "弁"

    def test_jinmei(self):
        """人名用漢字"""
        assert convert_old_kanji("堯") == "尭"
        assert convert_old_kanji("巖") == "巌"
        assert convert_old_kanji("聰") == "聡"

    def test_variants(self):
        """異体字"""
        assert convert_old_kanji("髙橋") == "高橋"
        assert convert_old_kanji("𠮷田") == "吉田"
        assert convert_old_kanji("﨑") == "崎"

    def test_no_change_for_modern(self):
        """新字体テキストは変化しない"""
        text = "現代の日本語テキスト"
        assert convert_old_kanji(text) == text

    def test_empty_string(self):
        assert convert_old_kanji("") == ""

    def test_ascii(self):
        """ASCII文字は変化しない"""
        text = "Hello, World! 123"
        assert convert_old_kanji(text) == text

    def test_mixed(self):
        """漢字混じりの文"""
        text = "大日本帝國憲法ニ基ヅク"
        result = convert_old_kanji(text)
        assert "国" in result  # 國→国
        assert "ニ基ヅク" in result  # 仮名は変化しない

    def test_type_error(self):
        """str以外の入力でTypeError"""
        import pytest
        with pytest.raises(TypeError):
            convert_old_kanji(123)


class TestFindOldKanji:
    """find_old_kanji のテスト"""

    def test_find_basic(self):
        found = find_old_kanji("國")
        assert len(found) == 1
        assert found[0] == ("國", "国", 0)

    def test_find_multiple(self):
        found = find_old_kanji("國會")
        assert len(found) == 2

    def test_find_empty(self):
        found = find_old_kanji("現代語")
        assert len(found) == 0


class TestGetKanjiTable:
    """get_kanji_table のテスト"""

    def test_returns_dict(self):
        table = get_kanji_table()
        assert isinstance(table, dict)

    def test_all_single_char(self):
        """全エントリが1文字→1文字"""
        table = get_kanji_table()
        for k, v in table.items():
            assert len(k) == 1, f"キーが1文字でない: {k!r}"
            assert len(v) == 1, f"値が1文字でない: {v!r}"

    def test_no_identity(self):
        """同一字形ペアがない"""
        table = get_kanji_table()
        for k, v in table.items():
            assert k != v, f"同一字形ペア: {k!r} → {v!r}"

    def test_contains_joyo(self):
        """常用漢字が含まれている"""
        table = get_kanji_table()
        assert "國" in table
        assert table["國"] == "国"
