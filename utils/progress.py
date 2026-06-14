"""進捗表示（スピナー/進捗バー）の共通ヘルパー（改善案 D2）

OCR推論やLLM口語体変換の長い待ち時間に「動いている」体感を出すための進捗表示を
ここにまとめる。rich はこのモジュール内に閉じ込め、呼び出し側は ``spinner()`` /
``track()`` だけを使う。

非TTY（パイプ・リダイレクト）/ ``NO_COLOR`` 環境変数 / 設定OFF のときは rich を使わず
従来どおりの print にフォールバックする（ログ出力やリダイレクトでも壊れない）。
判定の思想は ``scripts/diff_viewer.py`` の ``_should_use_color`` に倣うが、参照する
設定キーが違う（diff は ``diff.color``、進捗は ``progress.enabled``）ため独立実装する。

使い方:
    from utils.progress import spinner, track, progress_active

    with spinner("OCR推論中 ..."):       # 所要時間が読めない待ち
        result = client.ocr(path)

    for chunk in track(chunks, total=len(chunks), description="変換中"):  # 件数既知ループ
        ...
"""

import os
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from utils.config import CONFIG

T = TypeVar("T")


def _progress_enabled() -> bool:
    """進捗表示（rich）を使うかを判定する。

    NO_COLOR 環境変数 / 設定OFF / 非tty（パイプ・リダイレクト）のいずれかなら
    無効にして、従来の print フォールバックに落とす。
    """
    if os.environ.get("NO_COLOR"):
        return False
    if not CONFIG.get("progress.enabled", True):
        return False
    return sys.stdout.isatty()


# 呼び出し側が「進捗表示が有効か」を見て従来 print を出し分けるための公開名。
progress_active = _progress_enabled


@contextmanager
def spinner(message: str) -> Iterator[None]:
    """所要時間が読めない待ち（OCR推論など）向けのスピナー。

    有効時は rich の Status でくるくる回し、ブロックを抜けると消える。
    無効時は message を1行 print するだけ（従来挙動を維持）。
    例外が出ても ``with`` が確実に表示を閉じる。

    Args:
        message: 実行中に表示するメッセージ。
    """
    if not _progress_enabled():
        print(message)
        yield
        return

    # フォールバック経路では rich を読み込まないよう関数内で遅延 import する。
    from rich.console import Console

    spinner_name = CONFIG.get("progress.spinner", "dots")
    console = Console()
    with console.status(message, spinner=spinner_name):
        yield


def track(iterable: Iterable[T], *, total: int | None, description: str) -> Iterator[T]:
    """件数の分かるループ（チャンク・複数件処理）向けの進捗バー。

    有効時は ``rich.progress.track`` でバー表示。無効時はそのまま素通しで yield する
    （呼び出し側が従来の print を出すことでフォールバックになる）。

    Args:
        iterable: 反復対象。
        total: 総件数（バーの分母）。不明なら None。
        description: バー左に出す説明ラベル。

    Yields:
        iterable の各要素。
    """
    if not _progress_enabled():
        yield from iterable
        return

    from rich.progress import track as rich_track

    yield from rich_track(iterable, total=total, description=description)
