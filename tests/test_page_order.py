"""画像のページ順（D5）のテスト

自然順のキー、画像の列挙、並べ方の指定、名前順と更新日時順の食い違いの検知を確認する。
実ファイルは tmp_path に作る空ファイルで足りる（画像として読むことはしない）。
更新日時は os.utime で設定する。
"""

import os
import random
import unicodedata
from pathlib import Path

import pytest

from utils.page_order import (
    first_mismatch,
    list_images,
    natural_key,
    sort_pages,
)


def _sorted_names(names: list[str]) -> list[str]:
    """名前のリストを自然順に並べて名前で返す（ファイルの実体は不要）"""
    return [p.name for p in sorted((Path(n) for n in names), key=natural_key)]


def _touch(folder: Path, name: str, mtime: int | None = None) -> Path:
    """空ファイルを作り、指定があれば更新日時（秒）を設定する"""
    path = folder / name
    path.write_bytes(b"")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


# ---------- natural_key: 期待順になる名前の形式 ----------


@pytest.mark.parametrize(
    "expected",
    [
        pytest.param(["1.png", "2.png", "9.png", "10.png", "11.png"], id="0埋めなし連番"),
        pytest.param(["p001.png", "p002.png", "p010.png", "p100.png"], id="pNNN"),
        pytest.param(["p998.png", "p999.png", "p1000.png", "p1001.png"], id="p999を超える"),
        pytest.param(["page9.png", "page10.png", "page11.png"], id="接頭辞つき"),
        pytest.param(
            [
                "スクリーンショット 2026-09-27 9.05.03.png",
                "スクリーンショット 2026-09-27 9.59.59.png",
                "スクリーンショット 2026-09-27 10.05.03.png",
                "スクリーンショット 2026-09-27 22.07.27.png",
            ],
            id="スクショ名の時刻が1桁と2桁",
        ),
        pytest.param(
            [
                "スクリーンショット 2026-09-27 22.07.27.png",
                "スクリーンショット 2026-09-27 22.07.27 (2).png",
                "スクリーンショット 2026-09-27 22.07.27 (3).png",
                "スクリーンショット 2026-09-27 22.07.28.png",
            ],
            id="同じ秒の連番つき",
        ),
        pytest.param(
            [
                "スクリーンショット 2026-09-27 午前9.05.03.png",
                "スクリーンショット 2026-09-27 午前11.59.00.png",
                "スクリーンショット 2026-09-27 午後0.05.00.png",
                "スクリーンショット 2026-09-27 午後1.05.03.png",
            ],
            id="日本語の12時間表示",
        ),
        pytest.param(["scan.png", "scan (1).png", "scan (2).png", "scan (10).png"], id="重複ダウンロード"),
        pytest.param(["頁１.png", "頁２.png", "頁１０.png"], id="全角数字"),
        pytest.param(["P1.png", "p2.png", "P3.png"], id="大文字小文字の混在"),
        pytest.param(["1.png", "2.jpg", "3.png", "10.jpg"], id="拡張子の混在"),
        pytest.param(["IMG_0998.JPG", "IMG_0999.JPG", "IMG_1000.JPG"], id="iPhone連番"),
    ],
)
def test_natural_order(expected):
    """期待順を入力の並びを変えて渡しても、期待順に並ぶ"""
    shuffled = expected[:]
    random.Random(0).shuffle(shuffled)
    assert _sorted_names(shuffled) == expected
    assert _sorted_names(expected[::-1]) == expected


def test_natural_order_real_input_1_to_32():
    """実物の input/ と同じ 1.png〜32.png が番号順になる（文字列順だと31枚がずれる）"""
    expected = [f"{i}.png" for i in range(1, 33)]
    assert sorted(expected) != expected  # 従来の文字列順では崩れる
    assert _sorted_names(sorted(expected)) == expected


# ---------- natural_key: 落とし穴 ----------


def test_superscript_digit_does_not_raise():
    """「²」は isdigit() が真だが int() できない。例外を出さず並べられる"""
    names = ["a1.png", "a².png", "a2.png", "b.png"]
    assert len(_sorted_names(names)) == len(names)


def test_same_number_has_stable_order_regardless_of_input_order():
    """数値が同じ名前（01 と 1、全角と半角）でも、入力の並びによらず同じ順になる"""
    names = ["1.png", "01.png", "１.png", "001.png"]
    first = _sorted_names(names)
    assert _sorted_names(names[::-1]) == first
    assert _sorted_names(sorted(names)) == first
    # 桁数の少ない方が先（1 → 01 → 001）
    assert first.index("1.png") < first.index("01.png") < first.index("001.png")


def test_nfc_and_nfd_names_sort_to_same_position():
    """濁点の表し方（NFC / NFD）が違っても同じ位置に並ぶ"""
    nfc = unicodedata.normalize("NFC", "ガ2.png")
    nfd = unicodedata.normalize("NFD", "ガ2.png")
    assert nfc != nfd
    assert natural_key(Path(nfc))[0] == natural_key(Path(nfd))[0]
    names = [unicodedata.normalize("NFD", "ガ10.png"), nfc, "ガ1.png"]
    assert [unicodedata.normalize("NFC", n) for n in _sorted_names(names)] == [
        "ガ1.png",
        "ガ2.png",
        "ガ10.png",
    ]


def test_narrow_nbsp_before_am_pm_is_normalized():
    """macOS の英語名にある U+202F（AM/PM 前の特殊な空白）が通常の空白と同じ扱いになる"""
    plain = Path("Screenshot 2026-09-27 at 9.05.03 AM.png")
    narrow = Path("Screenshot 2026-09-27 at 9.05.03 AM.png")
    assert natural_key(plain)[0] == natural_key(narrow)[0]


def test_extension_is_excluded_from_name_comparison():
    """拡張子を除いて比べる（拡張子込みだと「X (2).png」が「X.png」より前に来る）"""
    assert _sorted_names(["X (2).png", "X.png"]) == ["X.png", "X (2).png"]


# ---------- list_images ----------


def test_list_images_natural_order_and_all_supported_formats(tmp_path):
    """OCR が受け付ける形式（.tif / .webp を含む）を自然順で返し、画像以外は除く"""
    for name in ["10.png", "2.tif", "1.png", "3.webp", "4.JPG", "memo.txt", "5.heic"]:
        _touch(tmp_path, name)
    assert [p.name for p in list_images(tmp_path)] == [
        "1.png",
        "2.tif",
        "3.webp",
        "4.JPG",
        "10.png",
    ]


def test_list_images_skips_hidden_files_and_directories(tmp_path):
    """隠しファイル（._1.png）と、画像のような名前のフォルダ（old.png/）は含めない"""
    _touch(tmp_path, "1.png")
    _touch(tmp_path, "2.png")
    _touch(tmp_path, "._1.png")
    _touch(tmp_path, ".hidden.png")
    (tmp_path / "old.png").mkdir()
    assert [p.name for p in list_images(tmp_path)] == ["1.png", "2.png"]


def test_list_images_empty_folder(tmp_path):
    assert list_images(tmp_path) == []


def test_list_images_returns_paths_under_folder(tmp_path):
    """返すパスは folder 配下のパス（後段でそのまま開ける）"""
    _touch(tmp_path, "1.png")
    assert list_images(tmp_path) == [tmp_path / "1.png"]


# ---------- sort_pages ----------


def test_sort_pages_name(tmp_path):
    paths = [_touch(tmp_path, n) for n in ["10.png", "1.png", "2.png"]]
    assert [p.name for p in sort_pages(paths, "name")] == ["1.png", "2.png", "10.png"]


def test_sort_pages_mtime_oldest_first(tmp_path):
    """更新日時の古い順（名前順とは無関係）"""
    a = _touch(tmp_path, "a.png", mtime=3000)
    b = _touch(tmp_path, "b.png", mtime=1000)
    c = _touch(tmp_path, "c.png", mtime=2000)
    assert sort_pages([a, b, c], "mtime") == [b, c, a]


def test_sort_pages_mtime_distinguishes_sub_second(tmp_path):
    """秒未満の差も区別する（連写の画像が秒で丸められて同値にならない）"""
    a = _touch(tmp_path, "a.png")
    b = _touch(tmp_path, "b.png")
    os.utime(a, ns=(0, 1_000_000_000_500_000_000))
    os.utime(b, ns=(0, 1_000_000_000_100_000_000))
    assert sort_pages([a, b], "mtime") == [b, a]


def test_sort_pages_mtime_ties_use_natural_order(tmp_path):
    """更新日時がすべて同じなら自然順（文字列順ではない）"""
    paths = [_touch(tmp_path, n, mtime=5000) for n in ["10.png", "2.png", "1.png"]]
    assert [p.name for p in sort_pages(paths, "mtime")] == ["1.png", "2.png", "10.png"]


def test_sort_pages_does_not_modify_input(tmp_path):
    paths = [_touch(tmp_path, n) for n in ["10.png", "1.png"]]
    snapshot = paths[:]
    sort_pages(paths, "name")
    assert paths == snapshot


def test_sort_pages_unknown_order_lists_valid_values(tmp_path):
    with pytest.raises(ValueError) as exc:
        sort_pages([_touch(tmp_path, "1.png")], "random")
    assert "name" in str(exc.value) and "mtime" in str(exc.value)


# ---------- first_mismatch ----------


def test_first_mismatch_reports_first_differing_position(tmp_path):
    """名前順 1,2,3 に対して更新日時順 1,3,2 → 2番目で食い違う"""
    p1 = _touch(tmp_path, "1.png", mtime=1000)
    p2 = _touch(tmp_path, "2.png", mtime=3000)
    p3 = _touch(tmp_path, "3.png", mtime=2000)
    m = first_mismatch([p1, p2, p3])
    assert m is not None
    assert m.position == 2
    assert m.by_name == p2
    assert m.by_mtime == p3


def test_first_mismatch_is_none_when_orders_agree(tmp_path):
    paths = [_touch(tmp_path, f"{i}.png", mtime=1000 * i) for i in range(1, 6)]
    assert first_mismatch(paths) is None


def test_first_mismatch_is_none_when_all_mtimes_equal(tmp_path):
    """更新日時がすべて同じ（zip 展開など）なら食い違いとして扱わない"""
    paths = [_touch(tmp_path, n, mtime=5000) for n in ["1.png", "2.png", "10.png"]]
    assert first_mismatch(paths) is None


def test_first_mismatch_is_none_for_single_image(tmp_path):
    assert first_mismatch([_touch(tmp_path, "1.png")]) is None


def test_first_mismatch_ignores_input_order(tmp_path):
    """渡す並びにかかわらず、名前の自然順を基準に比べる"""
    p1 = _touch(tmp_path, "1.png", mtime=1000)
    p2 = _touch(tmp_path, "2.png", mtime=2000)
    p10 = _touch(tmp_path, "10.png", mtime=3000)
    assert first_mismatch([p10, p1, p2]) is None


def test_first_mismatch_is_none_when_mtime_unreadable(tmp_path):
    """更新日時を読めないファイルがあっても例外にせず None（警告のための検知なので）"""
    p1 = _touch(tmp_path, "1.png")
    missing = tmp_path / "2.png"  # 作らない
    assert first_mismatch([p1, missing]) is None
