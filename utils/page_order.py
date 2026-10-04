"""
画像のページ順 — 列挙・並べ替え・食い違いの検知

複数の画像を1件の文書に結合するときの「どの画像を・どの順で読むか」を決める。
画面出力や対話は持たない（呼び出し側の scripts/ocr_vision_llm.py が担当）。

並べ方は2種類:
    name  ファイル名の自然順（数字部分を数値として比べる。2.png は 10.png より前）
    mtime 更新日時の古い順（同じ日時なら自然順）

自然順にするのは、0埋めのない連番（1.png … 10.png）を文字列順に並べると
1, 10, 11, …, 2 となり、ページが黙って入れ替わるため。
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from utils.ollama_client import SUPPORTED_EXTENSIONS

ORDER_CHOICES = ("name", "mtime")

_DIGITS = re.compile(r"(\d+)")


def natural_key(path: Path) -> tuple:
    """自然順の並べ替えキーを返す

    - 拡張子を除いた名前（stem）で比べる。拡張子込みだと
      「X (2).png」が「X.png」より前に来てしまう（空白が「.」より前のため）
    - NFKC で全角英数字・濁点の表し方の違い・AM/PM 前の特殊な空白をそろえ、
      casefold で大文字小文字の違いを無視する
    - 「文字・数字・文字…」の交互に分け、各要素を (種別, 値, 桁数) の組にする。
      種別を先頭に置くので、文字と数値が直接比べられて TypeError になることがない
    - 数値が同じ名前（1.png と 01.png、全角と半角）は、桁数 → 拡張子 →
      元の名前の順で決める。同じファイルの集合なら常に同じ順になる
    """
    stem = unicodedata.normalize("NFKC", path.stem).casefold()
    tokens = tuple(
        (1, int(part), len(part)) if i % 2 else (0, part, 0)
        for i, part in enumerate(_DIGITS.split(stem))
    )
    return (tokens, path.suffix.lower(), path.name)


def list_images(folder: Path) -> list[Path]:
    """フォルダ直下の画像を自然順で返す

    OCR が受け付ける形式（ollama_client.SUPPORTED_EXTENSIONS）の通常ファイルだけを
    対象にする。名前が「.」で始まる隠しファイル（._1.png など）と、
    画像のような名前のフォルダ（x.png/）は含めない。
    """
    images = [
        f
        for f in folder.iterdir()
        if f.suffix.lower() in SUPPORTED_EXTENSIONS
        and not f.name.startswith(".")
        and f.is_file()
    ]
    return sort_pages(images, "name")


def sort_pages(paths: list[Path], order: str = "name") -> list[Path]:
    """画像を指定の並べ方で並べ替えて返す（元のリストは変えない）

    order="mtime" は更新日時（ナノ秒）の古い順。同じ日時のものは自然順にする。
    """
    if order == "name":
        return sorted(paths, key=natural_key)
    if order == "mtime":
        return sorted(paths, key=lambda p: (p.stat().st_mtime_ns, natural_key(p)))
    raise ValueError(
        f"未知の並べ方です: {order!r}（使えるのは: {', '.join(ORDER_CHOICES)}）"
    )


@dataclass(frozen=True)
class OrderMismatch:
    """名前順と更新日時順が最初に食い違う位置"""

    position: int  # 1始まりの番号
    by_name: Path  # その位置にある、名前順での画像
    by_mtime: Path  # その位置にある、更新日時順での画像


def first_mismatch(paths: list[Path]) -> OrderMismatch | None:
    """名前の自然順と更新日時の古い順が最初に食い違う位置を返す

    食い違いが無ければ None。更新日時が同じ画像どうしは自然順で並べるため、
    更新日時がそろっているだけ（zip 展開など）では食い違いにならない。
    更新日時を読めないファイルがあるときも None を返す（警告のための検知であり、
    ここで処理を止めない。読めないファイルは後段の OCR で失敗として扱われる）。
    """
    by_name = sort_pages(paths, "name")
    try:
        by_mtime = sort_pages(paths, "mtime")
    except OSError:
        return None
    for i, (a, b) in enumerate(zip(by_name, by_mtime), start=1):
        if a != b:
            return OrderMismatch(position=i, by_name=a, by_mtime=b)
    return None
