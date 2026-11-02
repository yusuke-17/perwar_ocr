"""漢字変換のテスト"""

import json
from importlib import resources
from pathlib import Path

import pytest

import senzen_word
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


# ---------- G10: 字形違いの旧字・俗字・人名用異体字 ----------

# 変換表の JSON（読み込み順）
_TABLE_FILES = [
    "joyo_old_new.json",
    "glyph_old_new.json",
    "zokuji.json",
    "jinmei.json",
    "variants.json",
]

# 常用漢字表に括弧書きされない字形違いの旧字（提案時の34字。監査で足した字は test_every_entry_converts で確かめる）
GLYPH_PAIRS = list(
    zip(
        "敎說脫銳悅閱歲絕吳娛戶內尙產姬旣淸靑鬪彥强揷敘澀獎戱吿查冰劒噐囘姊鄰",
        "教説脱鋭悦閲歳絶呉娯戸内尚産姫既清青闘彦強挿叙渋奨戯告査氷剣器回姉隣",
    )
)

# 俗字・略字（提案時の8字）
ZOKUJI_PAIRS = list(zip("塲寳舘竒刋畧蘆豬", "場宝館奇刊略芦猪"))


def _load_table_file(name: str) -> dict[str, str]:
    data_dir = resources.files("senzen_word.kanji") / "data"
    return json.loads((data_dir / name).read_text(encoding="utf-8"))


class TestGlyphAndZokuji:
    """字形違いの旧字と俗字の変換"""

    @pytest.mark.parametrize("old,new", GLYPH_PAIRS)
    def test_glyph_old_form(self, old, new):
        assert convert_old_kanji(old) == new

    @pytest.mark.parametrize("old,new", ZOKUJI_PAIRS)
    def test_zokuji(self, old, new):
        assert convert_old_kanji(old) == new

    def test_glyph_scenario(self):
        """仕様: 字形違いの旧字を含む原文"""
        assert senzen_word.convert("敎育ニ關スル勅語") == "教育に関スル勅語"
        assert senzen_word.convert("內務省") == "内務省"
        assert senzen_word.convert("歲出") == "歳出"

    def test_mixed_with_joyo_old_form(self):
        """仕様: 常用漢字表の旧字体と並んで現れる"""
        assert senzen_word.convert("說明書ノ產業ト國家") == "説明書の産業と国家"

    def test_zokuji_scenario(self):
        """仕様: 俗字を含む原文"""
        assert senzen_word.convert("會議ノ塲所") == "会議の場所"
        assert senzen_word.convert("圖書舘") == "図書館"
        assert senzen_word.convert("刋行") == "刊行"


class TestPlaceNameVariantsKept:
    """人名・地名用の異体字は変換しない"""

    @pytest.mark.parametrize("char", ["嵜", "碕"])
    def test_not_converted(self, char):
        assert convert_old_kanji(char) == char

    def test_place_name_scenario(self):
        """仕様: 地名の異体字（縣だけが県になる）"""
        assert senzen_word.convert("長嵜縣") == "長嵜県"
        assert senzen_word.convert("川碕町") == "川碕町"


class TestTableIntegrity:
    """変換表どうしの整合性"""

    def test_no_duplicate_keys_across_files(self):
        """同じキーが2つのファイルに無い"""
        seen: dict[str, str] = {}
        for name in _TABLE_FILES:
            for key in _load_table_file(name):
                assert key not in seen, f"{key!r} が {seen.get(key)} と {name} の両方にある"
                seen[key] = name

    def test_no_chain(self):
        """変換先がどの表のキーでもない（1回で最終の字に到達する）"""
        table = get_kanji_table()
        chained = {k: v for k, v in table.items() if v in table}
        assert chained == {}

    def test_idempotent(self):
        """仕様: 正規化を2回かけても旧字体の変換で字が変わらない"""
        text = "".join(get_kanji_table())
        once = convert_old_kanji(text)
        assert convert_old_kanji(once) == once

    def test_modern_text_unchanged(self):
        """仕様: 新字体だけの文章は漢字が1字も変わらない"""
        text = "教育に関する勅語。内務省の歳出、説明書の産業と国家、図書館の刊行"
        assert convert_old_kanji(text) == text

    def test_table_size(self):
        """常用 372・字形違い 35・俗字 42・人名用 9・異体字 75 の計 533 字（README の表と一致）"""
        assert len(get_kanji_table()) == 533

    @pytest.mark.parametrize("name", _TABLE_FILES)
    def test_every_entry_converts(self, name):
        """各ファイルの全エントリが、読み込まれた表でそのとおりに変換される"""
        for old, new in _load_table_file(name).items():
            assert convert_old_kanji(old) == new, f"{name}: {old!r} → {new!r}"


class TestKeepList:
    """「変換しない字」の一覧（tools/kanji_keep.json）"""

    KEEP_PATH = Path(__file__).resolve().parent.parent / "tools" / "kanji_keep.json"
    REASONS = {"人名地名", "簡体字", "別字", "書きかえ", "保留"}

    def _keep(self) -> dict[str, dict[str, str]]:
        return json.loads(self.KEEP_PATH.read_text(encoding="utf-8"))

    def test_not_in_table(self):
        """仕様: 同じ字が変換表と一覧の両方にない"""
        table = get_kanji_table()
        assert [c for c in self._keep() if c in table] == []

    def test_reason_and_note(self):
        """reason は5種のどれかで、note は空でない"""
        for char, entry in self._keep().items():
            assert len(char) == 1, f"キーが1文字でない: {char!r}"
            assert entry.get("reason") in self.REASONS, f"{char}: reason が不正 {entry!r}"
            assert entry.get("note", "").strip(), f"{char}: note が空"

    def test_place_name_variants_recorded(self):
        """仕様: 嵜・碕 は理由（人名地名）とともに一覧に載る"""
        keep = self._keep()
        assert keep["嵜"]["reason"] == "人名地名"
        assert keep["碕"]["reason"] == "人名地名"
