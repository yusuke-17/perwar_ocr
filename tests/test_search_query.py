"""検索クエリの解析と FTS5 式の組み立てのテスト

C2「OR/NOT検索」の追加にあたって新設。
sqlite3 と normalize_query だけで完結し、Ollama も外部通信も使わない。

対象文書は旧字体・カタカナ仮名遣い・歴史的仮名遣いを含むため、
すべての語（検索語・除外語・限定語）が同じ正規化を経ることを重点的に確認する。
"""

import sqlite3

import pytest

from utils.library_search import (
    FIELD_ALIASES,
    TRIGRAM_MIN_QUERY_CHARS,
    QuerySyntaxError,
    QueryTooShortError,
    build_match_expr,
    parse_query,
)


def expr(query: str) -> str:
    """クエリ文字列から FTS5 の MATCH 式を作る（テスト用の短縮）"""
    return build_match_expr(parse_query(query))


# ---------- カラム別名表 ----------


def test_field_aliases_point_to_known_columns():
    """別名表の変換先は FTS テーブルの実在カラムだけ"""
    from utils.library_search import _FTS_FIELDS

    columns = {name for _, name in _FTS_FIELDS}
    assert set(FIELD_ALIASES.values()) <= columns


def test_field_aliases_cover_all_searchable_columns():
    """検索対象の全カラムに少なくとも1つの別名がある"""
    from utils.library_search import _FTS_FIELDS

    columns = {name for _, name in _FTS_FIELDS}
    assert set(FIELD_ALIASES.values()) == columns


# ---------- AND（従来の挙動） ----------


def test_space_separated_terms_are_anded():
    assert expr("関東地方 震災被害") == '("関東地方" AND "震災被害")'


def test_full_width_space_is_a_separator():
    assert expr("関東地方　震災被害") == '("関東地方" AND "震災被害")'


def test_single_term_is_wrapped_in_parens():
    """単語1つでも括弧で包む（NOT を後から当てても優先順位が崩れない）"""
    assert expr("関東地方") == '("関東地方")'


# ---------- OR（モード切替） ----------


def test_or_switches_whole_group_to_or():
    assert expr("関東地方 OR 大阪府下") == '("関東地方" OR "大阪府下")'


def test_or_applies_to_all_terms_not_just_neighbors():
    """OR が1つでもあれば語群全体が OR になる（AND との混在を作らない）

    FTS5 の素の優先順位（NOT > AND > OR）だと
    "関東地方" OR ("大阪府下" AND "警察署") になり利用者の直感と食い違う。
    """
    assert expr("関東地方 OR 大阪府下 警察署") == (
        '("関東地方" OR "大阪府下" OR "警察署")'
    )


def test_multiple_or_tokens_are_idempotent():
    assert expr("関東地方 OR 大阪府下 OR 警察署") == (
        '("関東地方" OR "大阪府下" OR "警察署")'
    )


def test_or_after_not_does_not_switch_the_positive_group():
    """除外語側の OR は語群の結合方法を変えない（除外語は元から互いに OR）"""
    assert expr("関東地方 震災被害 NOT 大阪府下 OR 横浜港") == (
        '("関東地方" AND "震災被害") NOT ("大阪府下" OR "横浜港")'
    )


# ---------- NOT（除外） ----------


def test_not_excludes_following_terms():
    assert expr("震災被害 NOT 大阪府下") == '("震災被害") NOT ("大阪府下")'


def test_multiple_excludes_are_ored():
    """除外語が複数なら「いずれかを含む文書を除く」"""
    assert expr("震災被害 NOT 大阪府下 横浜港") == (
        '("震災被害") NOT ("大阪府下" OR "横浜港")'
    )


def test_positive_group_is_parenthesized_before_not():
    """語群を包んでから NOT を当てる（FTS5 の優先順位を結果に出さない）"""
    assert expr("関東地方 OR 大阪府下 NOT 横浜港") == (
        '("関東地方" OR "大阪府下") NOT ("横浜港")'
    )


def test_excludes_only_query_is_rejected():
    """除外語だけのクエリは FTS5 で表現できない（NOT は二項演算子）"""
    with pytest.raises(QuerySyntaxError, match="除外語だけ"):
        parse_query("NOT 大阪府下")


def test_repeated_not_is_rejected():
    """NOT の2回目は黙って無視せずエラーにする"""
    with pytest.raises(QuerySyntaxError, match="1回だけ"):
        parse_query("関東地方 NOT 大阪府下 NOT 横浜港")


# ---------- カラム限定 ----------


def test_field_limit_with_japanese_alias():
    assert expr("原文:罹災者") == '(({original} : "罹災者"))'


def test_field_limit_with_full_width_colon():
    assert expr("原文：罹災者") == '(({original} : "罹災者"))'


def test_field_limit_with_english_alias():
    assert expr("original:罹災者") == '(({original} : "罹災者"))'


def test_field_alias_is_case_insensitive_for_ascii():
    assert expr("ORIGINAL:罹災者") == '(({original} : "罹災者"))'


def test_field_limit_combines_with_plain_term():
    assert expr("原文:罹災者 警察署") == (
        '(({original} : "罹災者") AND "警察署")'
    )


def test_title_and_modern_aliases():
    assert expr("題名:関東大震災") == '(({title} : "関東大震災"))'
    assert expr("口語:被災者数") == '(({modern} : "被災者数"))'


def test_colon_in_body_text_is_not_a_field_limit():
    """本文由来のコロン（午前10:30 等）を限定指定と誤解しない"""
    parsed = parse_query("午前10:30 警察署")
    assert parsed.terms[0][0] is None
    assert "10" in parsed.terms[0][1]


def test_unknown_ascii_field_name_is_rejected():
    """ASCII英字だけの対象名は「書き間違い」とみなしてエラーにする"""
    with pytest.raises(QuerySyntaxError, match="検索対象の名前ではありません"):
        parse_query("body:関東地方")


def test_unknown_field_error_lists_available_aliases():
    with pytest.raises(QuerySyntaxError, match="原文"):
        parse_query("body:関東地方")


def test_field_limit_on_exclude_is_rejected():
    """除外は文書全体が対象。除外語への限定は受け付けない"""
    with pytest.raises(QuerySyntaxError, match="除外語に対象の限定"):
        parse_query("関東地方 NOT 原文:罹災者")


# ---------- 正規化（旧字体・歴史的仮名遣い） ----------


def test_search_term_is_normalized():
    """旧字体の検索語が新字体に揃う"""
    assert expr("關東地方") == '("関東地方")'


def test_exclude_term_is_normalized():
    """除外語も同じ正規化を経る（旧字体の原文を現代表記で除ける）"""
    assert expr("震災被害 NOT 橫濱港") == '("震災被害") NOT ("横浜港")'


def test_field_limited_term_is_normalized():
    """限定語も同じ正規化を経る"""
    assert expr("原文:罹災者 記錄簿") == (
        '(({original} : "罹災者") AND "記録簿")'
    )


def test_historical_kana_is_normalized_in_all_roles():
    """歴史的仮名遣いは検索語・除外語のどちらでも変換される"""
    parsed = parse_query("けふの記録 NOT けふの新聞")
    assert parsed.terms[0][1] == parsed.excludes[0].replace("新聞", "記録")


# ---------- 語の長さの検査 ----------


def test_short_search_term_is_rejected_with_role():
    with pytest.raises(QueryTooShortError, match="検索語"):
        parse_query("地震")


def test_short_exclude_term_is_rejected_with_role():
    with pytest.raises(QueryTooShortError, match="除外語"):
        parse_query("関東地方 NOT 大阪")


def test_short_field_limited_term_is_rejected_with_role():
    with pytest.raises(QueryTooShortError, match="限定語"):
        parse_query("原文:災害")


def test_length_is_checked_after_normalization():
    """正規化で字数が縮む語は、縮んだ後の長さで判定する

    「けふ」（3文字）は歴史的仮名遣いの変換で「きょう」になり、
    拗音を1音と数える正規化では最小文字数を割りうる。
    どちらに転んでも「正規化後の語」が示されることを確認する。
    """
    from utils.text_normalizer import normalize_query

    normalized = normalize_query("けふ")
    if len(normalized) < TRIGRAM_MIN_QUERY_CHARS:
        with pytest.raises(QueryTooShortError, match=normalized or "空"):
            parse_query("けふ")
    else:
        assert parse_query("けふ").terms == [(None, normalized)]


def test_empty_query_is_rejected():
    with pytest.raises(QueryTooShortError, match="空"):
        parse_query("   ")


# ---------- 生成した式が FTS5 で通ること ----------


@pytest.fixture
def fts():
    """テスト用コーパス（旧字体の原文つき）"""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE VIRTUAL TABLE search USING fts5("
        "id UNINDEXED, title, modern, original, tokenize='trigram');"
    )
    conn.executemany(
        "INSERT INTO search VALUES (?, ?, ?, ?)",
        [
            (
                "d1",
                "関東大震災の記録",
                "関東地方の大地震で被災者が多数出た。警察署が誘導した。",
                "関東地方ノ大地震ニテ罹災者多数警察署ガ誘導セリ",
            ),
            (
                "d2",
                "大阪府の報告",
                "大阪府下の警察署は治安維持に努めた。",
                "大阪府下ノ警察署ハ治安維持ニ努メタリ",
            ),
            (
                "d3",
                "横浜港の状況",
                "横浜港は壊滅的な被害を受けた。関東地方の一部である。",
                "横浜港ハ壊滅的被害ヲ受ク関東地方ノ一部ナリ",
            ),
        ],
    )
    yield conn
    conn.close()


def matches(fts, query: str) -> set[str]:
    rows = fts.execute(
        "SELECT id FROM search WHERE search MATCH ?", (expr(query),)
    ).fetchall()
    return {r[0] for r in rows}


def test_and_query_runs_on_fts5(fts):
    assert matches(fts, "関東地方 警察署") == {"d1"}


def test_or_query_runs_on_fts5(fts):
    assert matches(fts, "大阪府下 OR 横浜港") == {"d2", "d3"}


def test_not_query_runs_on_fts5(fts):
    assert matches(fts, "警察署 NOT 大阪府下") == {"d1"}


def test_multiple_excludes_run_on_fts5(fts):
    assert matches(fts, "関東地方 NOT 大阪府下 横浜港") == {"d1"}


def test_or_with_not_runs_on_fts5(fts):
    """語群を包んでから NOT を当てるので、OR の片方だけが除外されない"""
    assert matches(fts, "警察署 OR 横浜港 NOT 大阪府下") == {"d1", "d3"}


def test_field_limit_runs_on_fts5(fts):
    """原文にだけ残る語を狙える（口語化後には「被災者」しかない）"""
    assert matches(fts, "原文:罹災者") == {"d1"}
    assert matches(fts, "口語:罹災者") == set()


def test_field_limit_scope_does_not_leak_to_next_term(fts):
    """限定の効果が後続の語に漏れない

    「罹災者」は原文だけ、「被災者」は口語だけにある。限定が漏れていれば
    どちらかがゼロ件になる。
    """
    assert matches(fts, "原文:罹災者 被災者") == {"d1"}


def test_field_limited_and_plain_terms_combine(fts):
    assert matches(fts, "原文:罹災者 大阪府下") == set()


def test_double_quote_in_term_is_escaped(fts):
    """語に含まれるダブルクォートで構文が壊れない

    クォートごと1つの語として扱われるので、一致するのは本文に
    そのままクォート付きで現れる文書だけ（構文エラーにはならない）。
    """
    fts.execute('INSERT INTO search VALUES (\'d4\', \'x\', \'彼は"警察署"と言った\', \'\')')
    assert matches(fts, '"警察署"') == {"d4"}
