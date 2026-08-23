"""ライブラリ全文検索（LibraryIndex）のテスト

G5「検索インデックスが口語化後テキストのみ」／G6「差分更新が meta.json の
mtime のみ判定」の改修にあたって新設。改修前は library_search.py に
テストが1件も無く、FTSスキーマと差分更新を同時に触るため回帰の網を先に張る。

sqlite3 と normalize_text だけで完結し、Ollama も外部通信も使わない。
"""

import json
import os
import sqlite3

import pytest

from utils.library_search import LibraryIndex, QueryTooShortError

# ---------- フィクスチャ・ヘルパー ----------


def make_doc(
    root,
    doc_id,
    *,
    title="関東大震災の記録",
    modern="昨日の地震で多くの被災者が出ました。",
    ocr_raw="昨日ノ地震ニテ多クノ罹災者ヲ生ジタリ",
    created_at="2026-01-01T00:00:00+09:00",
):
    """最小構成の文書フォルダを作る

    ocr_raw に None を渡すと ocr_raw.txt を作らない（欠損ケースの再現）。
    modern に None を渡すと modern.txt を作らない（スキップ対象の再現）。
    """
    doc_dir = root / doc_id
    doc_dir.mkdir(parents=True)

    meta = {
        "schema_version": 1,
        "id": doc_id,
        "created_at": created_at,
        "title": title,
        "sources": ["source.png"],
    }
    (doc_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if modern is not None:
        (doc_dir / "modern.txt").write_text(modern, encoding="utf-8")
    if ocr_raw is not None:
        (doc_dir / "ocr_raw.txt").write_text(ocr_raw, encoding="utf-8")
    return doc_dir


def touch(path, *, delta=10.0):
    """mtime を確実に進める（同一秒内の書き換えでも差分検知させる）"""
    st = path.stat()
    os.utime(path, (st.st_atime + delta, st.st_mtime + delta))


@pytest.fixture
def library(tmp_path):
    """文書1件を持つライブラリ"""
    root = tmp_path / "library"
    root.mkdir()
    make_doc(root, "2026-01-01_test")
    return root


# ---------- update(): 追加・更新・削除・スキップ ----------


def test_update_adds_document(library):
    """新規文書が索引に追加される"""
    stats = LibraryIndex(library).update()
    assert stats.added == 1
    assert stats.updated == 0
    assert stats.removed == 0
    assert stats.skipped == 0


def test_update_is_idempotent(library):
    """変更が無ければ再索引されない"""
    idx = LibraryIndex(library)
    idx.update()
    stats = idx.update()
    assert stats.added == 0
    assert stats.updated == 0


def test_update_detects_meta_change(library):
    """meta.json が更新されたら再索引される"""
    idx = LibraryIndex(library)
    idx.update()
    touch(library / "2026-01-01_test" / "meta.json")
    stats = idx.update()
    assert stats.updated == 1


def test_update_removes_deleted_document(library):
    """フォルダごと消えた文書は索引からも消える"""
    idx = LibraryIndex(library)
    idx.update()

    doc_dir = library / "2026-01-01_test"
    for child in doc_dir.iterdir():
        child.unlink()
    doc_dir.rmdir()

    stats = idx.update()
    assert stats.removed == 1
    assert idx.stat()["document_count"] == 0


def test_update_skips_document_without_modern(tmp_path):
    """modern.txt が無い文書はスキップされる（本文が無いので索引の意味がない）"""
    root = tmp_path / "library"
    root.mkdir()
    make_doc(root, "2026-01-01_no_modern", modern=None)

    stats = LibraryIndex(root).update()
    assert stats.skipped == 1
    assert stats.added == 0


def test_update_ignores_dot_directories(library):
    """'.' 始まりのフォルダ（.index 等）は走査対象外"""
    hidden = library / ".backup"
    hidden.mkdir()
    (hidden / "meta.json").write_text("{}", encoding="utf-8")

    stats = LibraryIndex(library).update()
    assert stats.added == 1


# ---------- search() ----------


def test_search_finds_modern_term(library):
    """口語化後テキストの語で検索できる"""
    idx = LibraryIndex(library)
    idx.update()
    hits = idx.search("被災者")
    assert len(hits) == 1
    assert hits[0].id == "2026-01-01_test"


def test_search_returns_metadata(library):
    """検索結果に題名・作成日時・フォルダパスが載る"""
    idx = LibraryIndex(library)
    idx.update()
    (hit,) = idx.search("被災者")
    assert hit.title == "関東大震災の記録"
    assert hit.created_at == "2026-01-01T00:00:00+09:00"
    assert hit.dir.name == "2026-01-01_test"
    assert "被災者" in hit.snippet


def test_search_terms_are_anded(library):
    """スペース区切りの語は AND 検索"""
    idx = LibraryIndex(library)
    idx.update()
    assert len(idx.search("被災者 多くの")) == 1
    assert idx.search("被災者 存在しない語") == []


def test_search_no_hit_returns_empty(library):
    """一致しなければ空リスト"""
    idx = LibraryIndex(library)
    idx.update()
    assert idx.search("該当なし語句") == []


def test_search_rejects_short_query(library):
    """trigram が扱えない2文字以下の語は QueryTooShortError"""
    idx = LibraryIndex(library)
    idx.update()
    with pytest.raises(QueryTooShortError):
        idx.search("地震", limit=5)


def test_search_rejects_empty_query(library):
    """空のクエリは QueryTooShortError"""
    idx = LibraryIndex(library)
    idx.update()
    with pytest.raises(QueryTooShortError):
        idx.search("   ")


def test_search_respects_limit(tmp_path):
    """limit で件数が絞られる"""
    root = tmp_path / "library"
    root.mkdir()
    for i in range(3):
        make_doc(root, f"2026-01-0{i + 1}_doc")

    idx = LibraryIndex(root)
    idx.update()
    assert len(idx.search("被災者", limit=2)) == 2


# ---------- delete() / rebuild() / stat() ----------


def test_delete_removes_from_index(library):
    """delete() は索引から1件だけ消す（フォルダは消さない）"""
    idx = LibraryIndex(library)
    idx.update()

    assert idx.delete("2026-01-01_test") is True
    assert idx.search("被災者") == []
    assert (library / "2026-01-01_test").exists()


def test_delete_returns_false_when_absent(library):
    """存在しない ID の削除は False"""
    idx = LibraryIndex(library)
    idx.update()
    assert idx.delete("存在しないID") is False


def test_rebuild_recreates_index(library):
    """rebuild() は DB を作り直して全件を再索引する"""
    idx = LibraryIndex(library)
    idx.update()
    stats = idx.rebuild()
    assert stats.added == 1
    assert len(idx.search("被災者")) == 1


def test_stat_counts_documents(library):
    """stat() が文書数と DB サイズを返す"""
    idx = LibraryIndex(library)
    idx.update()
    s = idx.stat()
    assert s["document_count"] == 1
    assert s["db_size_bytes"] > 0
    assert s["latest_doc_mtime"] is not None


# ---------- G5: 正規化済み原文の索引 ----------


def test_search_finds_original_only_term(library):
    """口語化で言い換えられた語（原文にのみある語）で検索できる

    G5 の本丸。modern.txt は「被災者」、ocr_raw.txt は「罹災者」。
    改修前は「罹災者」でゼロ件だった。
    """
    idx = LibraryIndex(library)
    idx.update()
    hits = idx.search("罹災者")
    assert len(hits) == 1
    assert hits[0].id == "2026-01-01_test"


def test_search_finds_old_kanji_original_with_modern_query(tmp_path):
    """旧字体・歴史的仮名遣いの原文を現代表記のクエリで引ける"""
    root = tmp_path / "library"
    root.mkdir()
    make_doc(
        root,
        "2026-01-01_kyuji",
        modern="あいうえお",
        ocr_raw="關東大震災ノ當時ノ記錄",
    )

    idx = LibraryIndex(root)
    idx.update()
    assert len(idx.search("関東大震災")) == 1
    assert len(idx.search("の当時")) == 1  # 當→当（旧字体）
    assert len(idx.search("の記録")) == 1  # 錄→録（旧字体）


def test_search_still_finds_modern_only_term(library):
    """口語化後テキストにしか無い語も従来どおりヒットする（再現率を落とさない）"""
    idx = LibraryIndex(library)
    idx.update()
    assert len(idx.search("被災者")) == 1


def test_document_without_ocr_raw_is_still_indexed(tmp_path):
    """ocr_raw.txt が無くても文書は索引され、modern.txt 検索は機能する"""
    root = tmp_path / "library"
    root.mkdir()
    make_doc(root, "2026-01-01_no_raw", ocr_raw=None)

    idx = LibraryIndex(root)
    stats = idx.update()
    assert stats.added == 1
    assert stats.skipped == 0
    assert len(idx.search("被災者")) == 1
    assert idx.search("罹災者") == []  # 原文が無いので原文検索は当たらない


def test_normalized_title_is_searchable_but_display_stays_raw(tmp_path):
    """旧字体の題名を現代表記で引ける。表示される題名は生のまま"""
    root = tmp_path / "library"
    root.mkdir()
    make_doc(
        root,
        "2026-01-01_title",
        title="關東大震災ノ記錄",
        modern="あいうえお",
        ocr_raw="かきくけこ",
    )

    idx = LibraryIndex(root)
    idx.update()
    (hit,) = idx.search("関東大震災")
    assert hit.matched_fields == ("title",)
    assert hit.title == "關東大震災ノ記錄"  # 表示は正規化しない


def test_original_indexing_is_deterministic(library):
    """同じ原文なら索引される正規化済み原文は毎回同一"""
    idx = LibraryIndex(library)
    idx.update()
    first = _fetch_original(idx, "2026-01-01_test")

    idx.rebuild()
    assert _fetch_original(idx, "2026-01-01_test") == first
    assert first != ""


def _fetch_original(idx, doc_id):
    conn = sqlite3.connect(idx.db_path)
    try:
        (value,) = conn.execute(
            "SELECT original FROM search WHERE id = ?", (doc_id,)
        ).fetchone()
        return value
    finally:
        conn.close()


# ---------- G6: 索引入力3ファイルの変更検知 ----------


def test_update_detects_modern_edit(library):
    """modern.txt を手修正したら再索引される（G6の本丸）"""
    idx = LibraryIndex(library)
    idx.update()

    modern_path = library / "2026-01-01_test" / "modern.txt"
    modern_path.write_text("訂正後の本文です。", encoding="utf-8")
    touch(modern_path)

    stats = idx.update()
    assert stats.updated == 1
    assert len(idx.search("訂正後")) == 1
    assert idx.search("被災者") == []  # 古い本文では当たらない


def test_update_detects_ocr_raw_edit(library):
    """ocr_raw.txt を手修正したら再索引され、新しい原文の語で検索できる"""
    idx = LibraryIndex(library)
    idx.update()

    raw_path = library / "2026-01-01_test" / "ocr_raw.txt"
    raw_path.write_text("燒失セル家屋ノ数", encoding="utf-8")
    touch(raw_path)

    stats = idx.update()
    assert stats.updated == 1
    assert len(idx.search("家屋の数")) == 1  # 燒→焼（旧字体）、ノ→の（カタカナ助詞）
    assert idx.search("罹災者") == []


def test_update_detects_reverted_mtime(library):
    """mtime が「戻った」場合も検知する（最大値比較では取りこぼすケース）"""
    idx = LibraryIndex(library)
    idx.update()

    modern_path = library / "2026-01-01_test" / "modern.txt"
    modern_path.write_text("巻き戻した本文です。", encoding="utf-8")
    touch(modern_path, delta=-3600.0)  # mtime を過去へ

    stats = idx.update()
    assert stats.updated == 1
    assert len(idx.search("巻き戻した")) == 1


def test_update_skips_when_nothing_changed(library):
    """索引入力がどれも変わっていなければ再索引しない"""
    idx = LibraryIndex(library)
    idx.update()
    stats = idx.update()
    assert stats.added == 0
    assert stats.updated == 0


# ---------- 一致カラムの提示 ----------


def test_matched_fields_original_only(library):
    """原文のみ一致：抜粋は原文から出る"""
    idx = LibraryIndex(library)
    idx.update()
    (hit,) = idx.search("罹災者")
    assert hit.matched_fields == ("original",)
    assert "[罹災者]" in hit.snippet


def test_matched_fields_modern(library):
    """口語化後テキスト一致：抜粋は modern から出る"""
    idx = LibraryIndex(library)
    idx.update()
    (hit,) = idx.search("被災者")
    assert hit.matched_fields == ("modern",)
    assert "[被災者]" in hit.snippet


def test_matched_fields_both(library):
    """原文にも口語化後にもある語は両方が一致として載る"""
    idx = LibraryIndex(library)
    idx.update()
    (hit,) = idx.search("昨日の")
    assert set(hit.matched_fields) >= {"modern", "original"}


def test_snippet_markers_are_not_leaked(library):
    """一致判定に使う制御文字が抜粋に混入しない"""
    idx = LibraryIndex(library)
    idx.update()
    (hit,) = idx.search("罹災者")
    assert "\x02" not in hit.snippet
    assert "\x03" not in hit.snippet


# ---------- 索引形式の移行 ----------


def _create_legacy_db(library):
    """改修前（v1）のスキーマで search.db を作る"""
    db_path = library / ".index" / "search.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE documents (
                id          TEXT PRIMARY KEY,
                dir         TEXT NOT NULL,
                title       TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                mtime       REAL NOT NULL
            );
            CREATE VIRTUAL TABLE search USING fts5(
                id UNINDEXED, title, modern, tokenize = 'trigram'
            );
            """
        )
        doc_dir = library / "2026-01-01_test"
        conn.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?)",
            (
                "2026-01-01_test",
                str(doc_dir.resolve()),
                "関東大震災の記録",
                "2026-01-01T00:00:00+09:00",
                (doc_dir / "meta.json").stat().st_mtime,
            ),
        )
        conn.execute(
            "INSERT INTO search (id, title, modern) VALUES (?, ?, ?)",
            ("2026-01-01_test", "関東大震災の記録", "昨日の地震で多くの被災者が出ました。"),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_legacy_db_is_rebuilt_on_search(library, capsys):
    """旧形式の索引は検索時に自動で作り直される"""
    _create_legacy_db(library)

    idx = LibraryIndex(library)
    hits = idx.search("罹災者")  # 旧形式には無かった原文検索

    assert len(hits) == 1
    assert "再構築" in capsys.readouterr().out


def test_legacy_db_rebuild_leaves_library_files_untouched(library):
    """自動再構築はライブラリ内の資料ファイルを一切変更しない"""
    _create_legacy_db(library)

    doc_dir = library / "2026-01-01_test"
    before = {
        p.name: (p.stat().st_mtime, p.read_bytes())
        for p in sorted(doc_dir.iterdir())
    }

    LibraryIndex(library).search("罹災者")

    after = {
        p.name: (p.stat().st_mtime, p.read_bytes())
        for p in sorted(doc_dir.iterdir())
    }
    assert before == after


def test_legacy_db_is_rebuilt_on_stat(library, capsys):
    """stat() でも旧形式の索引は作り直される"""
    _create_legacy_db(library)

    s = LibraryIndex(library).stat()

    assert s["document_count"] == 1
    assert "再構築" in capsys.readouterr().out


def test_schema_version_is_stamped(library):
    """新規作成した索引には現行のスキーマ版が刻まれる"""
    from utils.library_search import INDEX_SCHEMA_VERSION

    idx = LibraryIndex(library)
    idx.update()

    conn = sqlite3.connect(idx.db_path)
    try:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
        assert version == INDEX_SCHEMA_VERSION
    finally:
        conn.close()


def test_no_rebuild_when_version_matches(library, capsys):
    """版が一致していれば再構築メッセージは出ない"""
    idx = LibraryIndex(library)
    idx.update()
    capsys.readouterr()

    idx.search("被災者")
    assert "再構築" not in capsys.readouterr().out


def test_index_db_is_created_under_dot_index(library):
    """DB は library/.index/search.db に作られる"""
    idx = LibraryIndex(library)
    idx.update()
    assert idx.db_path == library / ".index" / "search.db"
    assert idx.db_path.is_file()
    # sqlite ファイルとして開けること
    conn = sqlite3.connect(idx.db_path)
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM documents").fetchone()
        assert count == 1
    finally:
        conn.close()
