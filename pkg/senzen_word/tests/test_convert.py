"""トップレベルAPIの統合テスト"""

import senzen_word


class TestConvert:
    """senzen_word.convert() のテスト"""

    def test_kanji_conversion(self):
        """旧字体が新字体に変換される"""
        result = senzen_word.convert("國會")
        assert result == "国会"

    def test_kana_conversion(self):
        """歴史的仮名遣いが現代仮名遣いに変換される"""
        result = senzen_word.convert("さうだ")
        assert result == "そうだ"

    def test_particle_conversion(self):
        """カタカナ助詞がひらがなに変換される"""
        result = senzen_word.convert("島津氏ノ武術")
        assert "の" in result

    def test_all_layers(self):
        """全レイヤーが正しい順序で適用される"""
        # 旧字体 + カタカナ助詞
        text = "國會ニ於テ"
        result = senzen_word.convert(text)
        assert "国" in result  # 旧字体→新字体
        assert "にて" in result or "に" in result  # カタカナ助詞→ひらがな

    def test_real_document(self):
        """実際の戦前文書の一節"""
        text = "日本臣民ハ法律ノ定ムル所ニ從ヒ納稅ノ義務ヲ有ス"
        result = senzen_word.convert(text)
        # 從→従、稅→税 が変換されている
        assert "従" in result
        assert "税" in result
        # カタカナ助詞がひらがなに
        assert "は" in result
        assert "の" in result

    def test_hentaigana_feeds_historical_kana(self):
        """変体仮名の変換結果が、続く歴史的仮名遣い変換の入力になる

        U+1B017 (KA-1) + U+1B00A (U-1) → 「かう」→「こう」。
        変体仮名変換を歴史的仮名遣い変換より後ろに置くと「かう」で止まる。
        """
        result = senzen_word.convert("\U0001B017\U0001B00A")
        assert result == "こう"

    def test_hentaigana_with_old_kanji(self):
        """旧字体・変体仮名・カタカナ助詞が1つの文で同時に変換される"""
        # 關東 + 変体仮名「あ」 + カタカナ助詞「ノ」
        result = senzen_word.convert("關東\U0001B002ノ図")
        assert result == "関東あの図"

    def test_empty_string(self):
        assert senzen_word.convert("") == ""

    def test_modern_text_unchanged(self):
        """現代日本語テキストはほぼ変化しない"""
        text = "今日は良い天気です"
        assert senzen_word.convert(text) == text


class TestFind:
    """senzen_word.find() のテスト"""

    def test_returns_categorized(self):
        """各変換にカテゴリが付与される"""
        findings = senzen_word.find("國ヲ")
        categories = {f[3] for f in findings}
        # 國 → kanji, ヲ は助詞として検出される可能性
        assert "kanji" in categories

    def test_empty_for_modern(self):
        findings = senzen_word.find("現代語")
        assert len(findings) == 0

    def test_sorted_by_position(self):
        """結果が位置順にソートされている"""
        findings = senzen_word.find("國會ニ於テ")
        positions = [f[2] for f in findings]
        assert positions == sorted(positions)


class TestVersion:
    def test_version_exists(self):
        assert hasattr(senzen_word, "__version__")
        assert isinstance(senzen_word.__version__, str)
