"""変換箇所の可視化（B1）のテスト

差分計算の純粋関数（compute_segments / count_changes / render_inline）と、
ファイル不在時の異常系を確認する。
"""

import argparse

from scripts import diff_viewer
from scripts.diff_viewer import (
    compute_segments,
    count_changes,
    render_inline,
)


# ---------- compute_segments ----------


def test_compute_segments_replace():
    """旧字体→新字体（國→国）は replace セグメントになる"""
    segments = compute_segments("國", "国")
    replaces = [s for s in segments if s.kind == "replace"]
    assert len(replaces) == 1
    assert replaces[0].before == "國"
    assert replaces[0].after == "国"


def test_compute_segments_equal():
    """同一テキストは全 equal（変化なし）"""
    segments = compute_segments("変わらない", "変わらない")
    assert all(s.kind == "equal" for s in segments)
    assert "".join(s.before for s in segments) == "変わらない"


def test_compute_segments_insert_and_delete():
    """カタカナ助詞→ひらがな等で挿入・削除が検出される"""
    # 「國民ノ」→「国民の」: 國→国(replace), ノ→の(replace)
    segments = compute_segments("國民ノ", "国民の")
    kinds = [s.kind for s in segments]
    assert "equal" in kinds  # 「民」は不変
    assert "replace" in kinds


# ---------- count_changes ----------


def test_count_changes():
    """削除・追加文字数が期待通り（replace は両方に数える）"""
    segments = compute_segments("國民ノ義務", "国民の義務")
    deleted, added = count_changes(segments)
    # 國→国, ノ→の の2置換 → 削除2字・追加2字
    assert deleted == 2
    assert added == 2


def test_count_changes_no_change():
    """変化なしは 0字 / 0字"""
    deleted, added = count_changes(compute_segments("同じ", "同じ"))
    assert (deleted, added) == (0, 0)


# ---------- render_inline ----------


def test_render_no_color_has_no_ansi():
    """色なし時は ANSI エスケープを含まず、記号で変更箇所を示す"""
    segments = compute_segments("國", "国")
    out = render_inline(segments, use_color=False, context=None)
    assert "\033[" not in out
    assert "[-國-]" in out
    assert "{+国+}" in out


def test_render_color_has_ansi():
    """色あり時は ANSI エスケープを含む"""
    segments = compute_segments("國", "国")
    out = render_inline(segments, use_color=True, context=None)
    assert "\033[" in out


def test_render_context_shortens_long_equal():
    """変化のない長い区間は context 文字に省略される"""
    before = "あ" * 100 + "國"
    after = "あ" * 100 + "国"
    out = render_inline(
        compute_segments(before, after), use_color=False, context=10
    )
    assert "中略" in out
    # 省略により全体長は元より短くなる
    assert len(out) < len(before)


# ---------- run（異常系） ----------


def test_run_missing_files(tmp_path, capsys):
    """ocr_raw.txt / modern.txt が無いフォルダを渡すと戻り値1"""
    args = argparse.Namespace(
        target=str(tmp_path),
        library_root=str(tmp_path),
        stage="all",
        no_color=True,
        context=30,
    )
    assert diff_viewer.run(args) == 1
    assert "見つかりません" in capsys.readouterr().out


def test_run_two_stage_end_to_end(tmp_path, capsys):
    """ocr_raw.txt と modern.txt がそろえば2段階を表示して戻り値0"""
    doc = tmp_path / "2026-01-01_test"
    doc.mkdir()
    (doc / "ocr_raw.txt").write_text("國民ノ義務", encoding="utf-8")
    (doc / "modern.txt").write_text("国民の義務です", encoding="utf-8")
    args = argparse.Namespace(
        target="2026-01-01_test",
        library_root=str(tmp_path),
        stage="all",
        no_color=True,
        context=30,
    )
    assert diff_viewer.run(args) == 0
    out = capsys.readouterr().out
    assert "段階1" in out
    assert "段階2" in out
