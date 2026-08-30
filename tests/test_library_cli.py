"""検索結果の表示層（scripts/library.py）のテスト

C3「スニペット改善」で、抜粋の強調が「意味（一致箇所）」と
「表現（ANSI色 / JSON の位置情報）」に分かれた。その変換を押さえる。

CLI 引数のパースもここで確認する。演算子を含む語（OR / NOT / 原文:語）が
argparse の nargs="+" を素通りすることは、記号（-除外）を採らなかった理由
そのものなので回帰の網を張っておく。
"""

import argparse
import json

import pytest

from scripts.library import (
    _hit_to_dict,
    _matched_summary,
    _render_snippet,
    add_find_arguments,
)
from utils.library_search import MARK_CLOSE, MARK_OPEN, SearchHit
from utils.terminal import MATCH, RESET


def marked(text: str) -> str:
    """`<警察署>` 記法をマーカ付き文字列に変換する（テストを読みやすくする）"""
    return text.replace("<", MARK_OPEN).replace(">", MARK_CLOSE)


def make_hit(snippet="", **kwargs):
    from pathlib import Path

    defaults = dict(
        id="2026-01-01_test",
        dir=Path("library/2026-01-01_test"),
        title="関東大震災の記録",
        snippet=snippet,
        created_at="2026-01-01T00:00:00+09:00",
        matched_fields=("modern",),
        match_counts={"title": 0, "modern": 1, "original": 0},
    )
    defaults.update(kwargs)
    return SearchHit(**defaults)


# ---------- 抜粋のレンダリング ----------


def test_snippet_without_color_drops_markers():
    assert _render_snippet(marked("大阪府下の<警察署>は"), False) == "大阪府下の警察署は"


def test_snippet_with_color_wraps_match():
    out = _render_snippet(marked("大阪府下の<警察署>は"), True)
    assert out == f"大阪府下の{MATCH}警察署{RESET}は"


def test_plain_text_is_identical_with_and_without_color():
    """色を剥がした本文は色付き時と一致する（欠落しない）"""
    source = marked("<関東>地方の<震災>被害")
    colored = _render_snippet(source, True)
    plain = _render_snippet(source, False)
    assert colored.replace(MATCH, "").replace(RESET, "") == plain


def test_multiple_matches_are_each_wrapped():
    out = _render_snippet(marked("<警察署>と<警察署>"), True)
    assert out.count(MATCH) == 2
    assert out.count(RESET) == 2


def test_body_brackets_are_not_treated_as_markers():
    """本文に元からある角括弧は強調と混同されない"""
    out = _render_snippet(marked("[備考]の<警察署>"), False)
    assert out == "[備考]の警察署"


def test_stray_open_marker_is_dropped():
    """対にならない開始マーカは強調にせず、マーカ文字ごと落とす"""
    text = f"あ{MARK_OPEN}い警察署う"
    assert _render_snippet(text, True) == "あい警察署う"


def test_stray_close_marker_is_dropped():
    text = f"あい{MARK_CLOSE}警察署う"
    assert _render_snippet(text, True) == "あい警察署う"


def test_unclosed_marker_does_not_color_rest_of_snippet():
    """閉じ忘れたマーカで抜粋の残り全部が着色されない"""
    text = f"あ{MARK_OPEN}いうえお"
    out = _render_snippet(text, True)
    assert MATCH not in out
    assert out == "あいうえお"


# ---------- 一致の要約 ----------


def test_matched_summary_lists_fields_and_counts():
    hit = make_hit(
        matched_fields=("modern", "original"),
        match_counts={"title": 0, "modern": 1, "original": 3},
    )
    assert _matched_summary(hit) == "口語1 / 原文3"


def test_matched_summary_omits_unmatched_fields():
    hit = make_hit(
        matched_fields=("original",),
        match_counts={"title": 0, "modern": 0, "original": 2},
    )
    assert _matched_summary(hit) == "原文2"


# ---------- JSON 出力 ----------


def test_json_snippet_has_no_display_symbols():
    d = _hit_to_dict(make_hit(marked("大阪府下の<警察署>は")))
    assert d["snippet"] == "大阪府下の警察署は"
    assert MARK_OPEN not in d["snippet"]
    assert "[" not in d["snippet"]


def test_json_carries_highlight_positions():
    d = _hit_to_dict(make_hit(marked("大阪府下の<警察署>は")))
    assert d["snippet_highlights"] == [[5, 8]]
    start, end = d["snippet_highlights"][0]
    assert d["snippet"][start:end] == "警察署"


def test_json_highlight_positions_survive_body_brackets():
    """本文に角括弧があっても位置がずれない"""
    d = _hit_to_dict(make_hit(marked("[備考]の<警察署>")))
    start, end = d["snippet_highlights"][0]
    assert d["snippet"][start:end] == "警察署"


def test_json_carries_match_counts_and_fields():
    d = _hit_to_dict(
        make_hit(
            matched_fields=("modern", "original"),
            match_counts={"title": 0, "modern": 1, "original": 3},
        )
    )
    assert d["matched_fields"] == ["modern", "original"]
    assert d["match_counts"] == {"title": 0, "modern": 1, "original": 3}


def test_json_output_is_serializable():
    payload = json.dumps([_hit_to_dict(make_hit(marked("<警察署>")))], ensure_ascii=False)
    assert "警察署" in payload


# ---------- CLI 引数のパース ----------


@pytest.fixture
def parser():
    p = argparse.ArgumentParser()
    add_find_arguments(p)
    return p


def test_plain_terms_parse(parser):
    assert parser.parse_args(["関東地方", "震災被害"]).query == ["関東地方", "震災被害"]


def test_or_operator_passes_through_argparse(parser):
    args = parser.parse_args(["関東地方", "OR", "大阪府下"])
    assert args.query == ["関東地方", "OR", "大阪府下"]


def test_not_operator_passes_through_argparse(parser):
    """NOT はダッシュ始まりでないので位置引数として届く

    記号（-大阪府下）を採らなかった理由がここ。argparse は `-` 始まりの語を
    未知オプションとして扱い、nargs="+" の位置引数には届かない。
    """
    args = parser.parse_args(["震災被害", "NOT", "大阪府下"])
    assert args.query == ["震災被害", "NOT", "大阪府下"]


def test_field_limit_passes_through_argparse(parser):
    assert parser.parse_args(["原文:罹災者"]).query == ["原文:罹災者"]


def test_dash_prefixed_term_is_not_accepted(parser):
    """記号による除外構文が使えないことの証拠（採用しなかった根拠）"""
    with pytest.raises(SystemExit):
        parser.parse_args(["震災被害", "-大阪府下"])


def test_snippet_option_defaults_from_config(parser):
    from utils.config import CONFIG

    assert parser.parse_args(["関東地方"]).snippet == CONFIG.get("search.snippet_chars")


def test_snippet_option_is_overridable(parser):
    assert parser.parse_args(["関東地方", "--snippet", "64"]).snippet == 64


def test_no_color_flag_exists(parser):
    assert parser.parse_args(["関東地方"]).no_color is False
    assert parser.parse_args(["関東地方", "--no-color"]).no_color is True


# ---------- 対話メニューの入力の受け渡し ----------


@pytest.mark.parametrize(
    "typed",
    [
        "関東地方 震災被害",
        "関東地方 OR 大阪府下",
        "震災被害 NOT 大阪府下 横浜港",
        "原文:罹災者 警察署",
        "関東地方　震災被害",  # 全角スペース区切り
    ],
)
def test_menu_input_survives_split_join_roundtrip(typed):
    """対話メニューの split() / " ".join() 往復で演算子入りクエリが壊れない

    scripts/cli.py の _menu_search は入力を split() して args.query に入れ、
    cmd_find が " ".join() で戻す。Python の str.split() は全角スペースも
    区切りとして扱うので、そこで表記が揃うことも含めて確認する。
    """
    from utils.library_search import build_match_expr, parse_query

    roundtripped = " ".join(typed.split())
    assert build_match_expr(parse_query(roundtripped)) == (
        build_match_expr(parse_query(typed))
    )


def test_menu_input_keeps_operators_as_separate_tokens():
    """演算子が他の語とくっついたり消えたりしない"""
    assert "関東地方 OR 大阪府下".split() == ["関東地方", "OR", "大阪府下"]
    assert "震災被害 NOT 大阪府下".split() == ["震災被害", "NOT", "大阪府下"]
