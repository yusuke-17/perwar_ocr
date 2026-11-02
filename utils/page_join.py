"""
ページの結合と、読み取れなかったページの目印

複数の画像を1件の文書にまとめるとき、ページの本文をどうつなぐかを決める（B3・G11）。
ページの境目を知っているのは結合する段階だけなので、ここで境目の扱いを決めて本文に表す。

つなぎ方:
    前のページの末尾が文末の記号で終わる → 空行を1つ挟む（段落の区切り）
    それ以外（文の途中でページが変わる） → 改行1つ（口語化の LLM に段落と誤解させない）
    字同士を直接つながないのは、ページ末尾のページ番号や柱が次のページの本文にくっつくため

目印:
    OCR に失敗したページ        〔第2頁 読み取り失敗（IMG_0002.png）〕
    処理しなかったページ（1枚）  〔第8頁 未処理（IMG_0008.png）〕
    処理しなかったページ（連続） 〔第8〜10頁 未処理〕
    目印の前後には空行を挟む。正規化・口語化・題名の取り出しは is_gap_marker で目印を見分け、
    目印の行を変えず、目印をまたいで処理しない。目印の形を知るのはこのモジュールだけにする。
"""

import re
from dataclasses import dataclass
from typing import Literal

# 文末とみなす記号。「）」は文の途中の注記でも閉じるので含めない
SENTENCE_ENDINGS = frozenset("。．！？」』")

PageStatus = Literal["ok", "failed", "unprocessed"]

# 行全体がこの形のときだけ目印とみなす。ファイル名に「〕」が入っても行末の「〕」で閉じる
_GAP_MARKER = re.compile(r"〔第\d+(?:〜\d+)?頁 (?:読み取り失敗|未処理)(?:（.*）)?〕")

_PARAGRAPH_BREAK = "\n\n"
_LINE_BREAK = "\n"


@dataclass
class PageEntry:
    """結合する1ページ分の情報

    Attributes:
        index: 元のページ順での番号（1始まり）
        source: 元画像のファイル名
        status: "ok"（読み取れた）/ "failed"（失敗）/ "unprocessed"（打ち切りで処理しなかった）
        text: 読み取った本文（status が "ok" のときだけ使う）
    """

    index: int
    source: str
    status: PageStatus
    text: str = ""


def gap_marker(
    status: Literal["failed", "unprocessed"],
    start: int,
    end: int | None = None,
    source: str = "",
) -> str:
    """読み取れなかったページの目印の行を作る

    Args:
        status: "failed" なら読み取り失敗、"unprocessed" なら未処理
        start: 最初のページ番号（1始まり）
        end: 未処理が続くときの最後のページ番号。1ページなら None か start と同じ
        source: ファイル名。範囲の目印（2ページ以上）では使わない
    """
    if status == "failed":
        return f"〔第{start}頁 読み取り失敗（{source}）〕"
    if end is None or end == start:
        return f"〔第{start}頁 未処理（{source}）〕"
    return f"〔第{start}〜{end}頁 未処理〕"


def is_gap_marker(line: str) -> bool:
    """行が読み取れなかったページの目印か（前後の空白は無視する）"""
    return _GAP_MARKER.fullmatch(line.strip()) is not None


def ends_sentence(text: str) -> bool:
    """本文が文末の記号で終わっているか（末尾の空白・改行は無視する）"""
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in SENTENCE_ENDINGS


def _trim_page(text: str) -> str:
    """ページ本文の先頭の改行と末尾の空白・改行を除く

    先頭の空白（全角の字下げなど）は本文の一部なので残す。
    """
    return text.lstrip("\r\n").rstrip()


def _blocks(entries: list[PageEntry]) -> list[tuple[bool, str]]:
    """ページを (目印か, 文字列) の並びにする。未処理の連続は1つの目印にまとめる"""
    blocks: list[tuple[bool, str]] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        if entry.status == "ok":
            text = _trim_page(entry.text)
            if text:  # 字の無いページは何も足さない（区切りも増やさない）
                blocks.append((False, text))
            i += 1
        elif entry.status == "failed":
            blocks.append((True, gap_marker("failed", entry.index, source=entry.source)))
            i += 1
        else:
            j = i
            while j + 1 < len(entries) and entries[j + 1].status == "unprocessed":
                j += 1
            blocks.append(
                (
                    True,
                    gap_marker(
                        "unprocessed",
                        entry.index,
                        entries[j].index,
                        source=entry.source,
                    ),
                )
            )
            i = j + 1
    return blocks


def join_pages(entries: list[PageEntry]) -> str:
    """ページの本文を元の順につなぎ、読み取れなかったページの位置に目印を入れる

    1ページだけ読み取れた文書（1枚の処理）は、OCR 結果をそのまま返す。
    """
    if len(entries) == 1 and entries[0].status == "ok":
        return entries[0].text

    blocks = _blocks(entries)
    if not blocks:
        return ""

    parts = [blocks[0][1]]
    for (prev_marker, prev), (cur_marker, cur) in zip(blocks, blocks[1:]):
        if prev_marker or cur_marker or ends_sentence(prev):
            parts.append(_PARAGRAPH_BREAK)
        else:
            parts.append(_LINE_BREAK)
        parts.append(cur)
    return "".join(parts)


def split_by_gap_markers(text: str) -> list[tuple[bool, str]]:
    """テキストを (目印か, 文字列) の並びに分ける

    目印が無ければ [(False, text)] をそのまま返す（目印の無い文章の処理を一切変えないため）。
    目印があれば、本文の区間は前後の改行を除いて返し、空の区間は返さない。
    join_pages の出力なら、文字列を "\\n\\n" でつなぐと元に戻る。
    """
    lines = text.split("\n")
    if not any(is_gap_marker(line) for line in lines):
        return [(False, text)]

    parts: list[tuple[bool, str]] = []
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip("\n")
        if body.strip():
            parts.append((False, body))
        buffer.clear()

    for line in lines:
        if is_gap_marker(line):
            flush()
            parts.append((True, line))
        else:
            buffer.append(line)
    flush()
    return parts
