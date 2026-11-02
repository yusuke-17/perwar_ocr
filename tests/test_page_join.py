"""ページの結合と目印（B3・G11）のテスト

結合の規則（文の途中は改行1つ・文末は空行）と、読み取れなかったページの目印の
生成・判定・分割を、純粋関数として直接確かめる。本文は縦書き・旧字体・カタカナ文語の
公文書を模した短い文字列で足りる。
"""

from utils.page_join import (
    PageEntry,
    gap_marker,
    is_gap_marker,
    join_pages,
    split_by_gap_markers,
)


def _ok(index: int, text: str) -> PageEntry:
    return PageEntry(index=index, source=f"IMG_{index:04d}.png", status="ok", text=text)


def _failed(index: int) -> PageEntry:
    return PageEntry(index=index, source=f"IMG_{index:04d}.png", status="failed")


def _unprocessed(index: int) -> PageEntry:
    return PageEntry(index=index, source=f"IMG_{index:04d}.png", status="unprocessed")


# ---------- 結合の規則（仕様「複数ページの本文の結合」） ----------


def test_mid_sentence_boundary_joins_with_single_newline():
    """文の途中でページが変わると、空行ではなく改行1つでつながる"""
    text = join_pages([_ok(1, "…第三條ニ依リ當分ノ間"), _ok(2, "施行スルコトヲ得。")])
    assert text == "…第三條ニ依リ當分ノ間\n施行スルコトヲ得。"


def test_sentence_end_boundary_keeps_blank_line():
    """句点で終わるページの後には空行が1つ入る"""
    text = join_pages([_ok(1, "…右及通牒候也。"), _ok(2, "陸軍省副官\n本文")])
    assert text == "…右及通牒候也。\n\n陸軍省副官\n本文"


def test_all_sentence_endings_keep_blank_line():
    for end in "。．！？」』":
        text = join_pages([_ok(1, f"前{end}"), _ok(2, "後")])
        assert text == f"前{end}\n\n後", end


def test_closing_paren_is_not_sentence_end():
    """「）」は注記でも閉じるので文末とみなさず、改行1つでつなぐ"""
    text = join_pages([_ok(1, "陸軍省（副官）"), _ok(2, "ヨリ")])
    assert text == "陸軍省（副官）\nヨリ"


def test_page_number_line_stays_on_its_own_line():
    """最後の行がページ番号でも、次のページの最初の字と同じ行にならない"""
    text = join_pages([_ok(1, "…當分ノ間\n一二"), _ok(2, "施行スルコトヲ得。")])
    assert text == "…當分ノ間\n一二\n施行スルコトヲ得。"
    assert "一二施" not in text


def test_single_page_is_returned_as_is():
    """1枚の処理は OCR 結果のままで、改行や空行を加えない"""
    raw = "陸軍省\n本文ノ途中\n"
    assert join_pages([_ok(1, raw)]) == raw


def test_page_edges_are_trimmed_but_inner_text_kept():
    """ページの先頭の改行と末尾の空白・改行だけを除き、字下げや中身は変えない"""
    text = join_pages([_ok(1, "\n　第一條 本文\n\n"), _ok(2, "　續キ  \n")])
    assert text == "　第一條 本文\n　續キ"


def test_empty_page_adds_nothing():
    """字の無いページがあっても区切りは増えない"""
    text = join_pages([_ok(1, "前ノ文"), _ok(2, "  \n"), _ok(3, "後ノ文。")])
    assert text == "前ノ文\n後ノ文。"


# ---------- 目印（仕様「読み取れなかったページの目印」） ----------


def test_failed_middle_page_gets_marker_between_blank_lines():
    text = join_pages([_ok(1, "…當分ノ間"), _failed(2), _ok(3, "依テ右回答ス")])
    assert text == (
        "…當分ノ間\n\n〔第2頁 読み取り失敗（IMG_0002.png）〕\n\n依テ右回答ス"
    )


def test_failed_first_page_starts_with_marker_without_leading_blank():
    text = join_pages([_failed(1), _ok(2, "陸軍省副官\n本文"), _ok(3, "續キ")])
    assert text == (
        "〔第1頁 読み取り失敗（IMG_0001.png）〕\n\n陸軍省副官\n本文\n續キ"
    )


def test_consecutive_failures_then_unprocessed_range():
    """5〜7枚目が失敗し、8〜10枚目を処理しなかった"""
    entries = [_ok(i, f"本文{i}") for i in range(1, 5)]
    entries += [_failed(i) for i in range(5, 8)]
    entries += [_unprocessed(i) for i in range(8, 11)]
    text = join_pages(entries)
    assert text == (
        "本文1\n本文2\n本文3\n本文4\n\n"
        "〔第5頁 読み取り失敗（IMG_0005.png）〕\n\n"
        "〔第6頁 読み取り失敗（IMG_0006.png）〕\n\n"
        "〔第7頁 読み取り失敗（IMG_0007.png）〕\n\n"
        "〔第8〜10頁 未処理〕"
    )
    assert not text.endswith("\n")


def test_single_unprocessed_page_has_file_name():
    text = join_pages([_ok(1, "本文。"), _unprocessed(2)])
    assert text == "本文。\n\n〔第2頁 未処理（IMG_0002.png）〕"


def test_all_success_has_no_marker():
    text = join_pages([_ok(1, "壹"), _ok(2, "貳"), _ok(3, "參")])
    assert not any(is_gap_marker(line) for line in text.splitlines())


def test_only_failures_gives_markers_only():
    text = join_pages([_failed(1), _failed(2)])
    assert text == (
        "〔第1頁 読み取り失敗（IMG_0001.png）〕\n\n〔第2頁 読み取り失敗（IMG_0002.png）〕"
    )


# ---------- 目印の判定 ----------


def test_gap_marker_formats():
    assert gap_marker("failed", 2, source="a.png") == "〔第2頁 読み取り失敗（a.png）〕"
    assert gap_marker("unprocessed", 8, source="b.png") == "〔第8頁 未処理（b.png）〕"
    assert gap_marker("unprocessed", 8, 8, source="b.png") == "〔第8頁 未処理（b.png）〕"
    assert gap_marker("unprocessed", 8, 10, source="b.png") == "〔第8〜10頁 未処理〕"


def test_is_gap_marker_accepts_generated_markers():
    for marker in (
        gap_marker("failed", 12, source="舊記ヰ号.png"),
        gap_marker("failed", 3, source="写真〕（2）.png"),
        gap_marker("unprocessed", 8, 10),
        gap_marker("unprocessed", 8, source="IMG_0008.png"),
    ):
        assert is_gap_marker(marker), marker
        assert is_gap_marker(f"  {marker}  ")


def test_is_gap_marker_rejects_similar_lines():
    for line in (
        "〔第2頁〕",
        "〔第2頁 読ミ取リ失敗〕",
        "本文〔第2頁 読み取り失敗（a.png）〕",
        "〔第2頁 読み取り失敗（a.png）〕ノ件",
        "〔註〕本文",
        "",
    ):
        assert not is_gap_marker(line), line


# ---------- 目印での分割 ----------


def test_split_without_marker_returns_text_unchanged():
    text = "\n陸軍省\n\n本文ノ途中\n"
    assert split_by_gap_markers(text) == [(False, text)]


def test_split_round_trips_join_output():
    entries = [_failed(1), _ok(2, "見出シ\n本文"), _failed(3), _failed(4)]
    entries += [_ok(5, "續キ。"), _ok(6, "次ノ段"), _unprocessed(7), _unprocessed(8)]
    text = join_pages(entries)
    parts = split_by_gap_markers(text)
    assert "\n\n".join(s for _, s in parts) == text
    assert [m for m, _ in parts] == [True, False, True, True, False, True]
    assert parts[4] == (False, "續キ。\n\n次ノ段")
