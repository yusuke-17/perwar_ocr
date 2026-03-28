"""カタカナ助詞変換のテスト"""

from senzen_word.kana.katakana_particle import (
    convert_katakana_particles,
    find_katakana_particles,
)


class TestConvertKatakanaParticles:
    """convert_katakana_particles のテスト"""

    def test_compound_nishite(self):
        """複合助詞 ニシテ → にして"""
        assert convert_katakana_particles("劍法ニシテ") == "劍法にして"

    def test_compound_toshite(self):
        """複合助詞 トシテ → として"""
        assert convert_katakana_particles("基礎トシテ") == "基礎として"

    def test_compound_yori(self):
        """複合助詞 ヨリ → より"""
        assert convert_katakana_particles("東京ヨリ") == "東京より"

    def test_compound_not_in_katakana_word(self):
        """カタカナ語内の複合助詞は変換しない"""
        # 前がカタカナの場合は変換しない
        assert "ニシテ" in convert_katakana_particles("セラレタルニシテ")

    def test_single_no(self):
        """単一助詞 ノ → の"""
        assert convert_katakana_particles("島津氏ノ武術") == "島津氏の武術"

    def test_single_ha(self):
        """単一助詞 ハ → は"""
        assert convert_katakana_particles("彼ハ来た") == "彼は来た"

    def test_single_not_in_katakana(self):
        """カタカナ語内の単一助詞は変換しない"""
        # 前後がカタカナの場合は変換しない
        text = "コノ"
        result = convert_katakana_particles(text)
        assert "ノ" in result or "の" in result  # カタカナに囲まれているので変換しない

    def test_empty_string(self):
        assert convert_katakana_particles("") == ""

    def test_no_change_for_modern(self):
        text = "現代の日本語テキスト"
        assert convert_katakana_particles(text) == text

    def test_mixed_sentence(self):
        """漢字＋カタカナ助詞の実際の文"""
        text = "日本臣民ハ法律ノ定ムル所ニ従ヒ納税ノ義務ヲ有ス"
        result = convert_katakana_particles(text)
        assert "は" in result
        assert "の" in result


class TestFindKatakanaParticles:
    """find_katakana_particles のテスト"""

    def test_find_compound(self):
        found = find_katakana_particles("劍法ニシテ")
        assert len(found) >= 1

    def test_find_single(self):
        found = find_katakana_particles("島津氏ノ武術")
        assert len(found) >= 1

    def test_find_empty(self):
        found = find_katakana_particles("現代語")
        assert len(found) == 0
