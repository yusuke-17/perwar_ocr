"""検索クエリ正規化（C1）のテスト

normalize_query() が照合用のサブセット変換のみ行うこと、および
旧字体クエリで新字体インデックスがヒットすること（取りこぼし解消）を確認する。
"""

import json
from pathlib import Path

import pytest

from utils.text_normalizer import normalize_query
from utils.library_search import LibraryIndex, QueryTooShortError


# ---------- normalize_query 単体 ----------


def test_old_kanji_to_new():
    """旧字体→新字体（國→国）"""
    assert normalize_query("國") == "国"
    assert normalize_query("大日本帝國") == "大日本帝国"
    assert normalize_query("關東大震災") == "関東大震災"


def test_historical_kana():
    """歴史的仮名遣い変換（ヰ→イ、字種はカタカナのまま）"""
    assert normalize_query("ヰタ") == "イタ"


def test_punctuation_not_converted():
    """句読点・空白整形は照合用正規化では行わない（検索語を歪めないため）"""
    # normalize_text なら "." → "。" になるが、クエリでは変換しない
    assert normalize_query("A.B") == "A.B"


def test_yoon_contraction_shrinks_length():
    """拗音縮約で文字数が縮む（クヮシ=3文字 → カシ=2文字）"""
    assert normalize_query("クヮシ") == "カシ"


# ---------- 検索との結合（取りこぼし解消の回帰テスト） ----------


def _make_doc(library_root: Path, doc_id: str, title: str, modern: str) -> None:
    """library_root 配下に最小の文書フォルダ（meta.json + modern.txt）を作る"""
    doc_dir = library_root / doc_id
    doc_dir.mkdir(parents=True)
    meta = {"title": title, "created_at": "2026-01-01"}
    (doc_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    (doc_dir / "modern.txt").write_text(modern, encoding="utf-8")


def test_old_kanji_query_hits_new_kanji_index(tmp_path):
    """新字体で保存された文書を、旧字体クエリで検索してヒットすること"""
    library_root = tmp_path / "library"
    library_root.mkdir()
    # インデックスには新字体「大日本帝国」が入っている
    _make_doc(library_root, "doc1", "テスト文書", "我等ハ大日本帝国ノ臣民ナリ")

    idx = LibraryIndex(library_root)
    idx.update()

    # 旧字体「大日本帝國」で検索しても拾える
    hits = idx.search("大日本帝國")
    assert len(hits) == 1
    assert hits[0].id == "doc1"


def test_normalized_too_short_query_raises(tmp_path):
    """正規化「後」に3文字未満になる語は QueryTooShortError"""
    library_root = tmp_path / "library"
    library_root.mkdir()
    idx = LibraryIndex(library_root)
    # "クヮシ" は3文字だが正規化後は "カシ"（2文字）→ trigram で扱えない
    with pytest.raises(QueryTooShortError):
        idx.search("クヮシ")
