"""
変体仮名 → 現代ひらがな 変換モジュール

Unicode 10.0 (2017) で追加された変体仮名（Hentaigana）ブロックの
文字を対応する現代ひらがなに変換する。

対象範囲:
  - Kana Supplement: U+1B002〜U+1B0FF (254文字)
  - Kana Extended-A: U+1B100〜U+1B11E (31文字)

各変体仮名のUnicode名から字母（元の漢字）と音を特定し、
対応する現代ひらがなにマッピングする。

データソース: data/hentaigana.json
  tools/gen_hentaigana.py が unicodedata の正式名から生成する。
  手で編集せず、生成スクリプトを直して再生成すること。
"""

from __future__ import annotations

import json
import threading
from importlib import resources
from typing import Mapping


# ---------- モジュールレベルキャッシュ ----------

_TABLE: Mapping[int, str] | None = None
_MAP: dict[str, str] | None = None
_INIT_LOCK = threading.Lock()


# ---------- データ読み込み ----------


def _load_hentaigana_table() -> dict[str, str]:
    """data/hentaigana.json を読み込む

    変換先は複数文字でも構わない（str.translate が許容する）。
    不正な行は黙って捨てず、原因が分かる形で ValueError を送出する。

    Raises:
        ValueError: キーが1文字でない、または値が文字列でない場合
    """
    data_dir = resources.files("senzen_word.kana") / "data"
    resource = data_dir / "hentaigana.json"
    content = resource.read_text(encoding="utf-8")
    raw = json.loads(content)

    table: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or len(key) != 1:
            raise ValueError(f"変換元は1文字である必要があります: {key!r}")
        if not isinstance(value, str):
            raise ValueError(f"変換先は文字列である必要があります: {key!r} -> {value!r}")
        table[key] = value

    return table


def _ensure_initialized() -> None:
    """変換テーブルを初期化する（スレッドセーフ）"""
    global _TABLE, _MAP
    if _TABLE is not None:
        return
    with _INIT_LOCK:
        if _TABLE is not None:
            return
        _MAP = _load_hentaigana_table()
        _TABLE = {ord(k): v for k, v in _MAP.items()}


# ---------- 公開関数 ----------


def convert_hentaigana(text: str) -> str:
    """
    変体仮名を現代ひらがなに変換する

    Args:
        text: 変換対象のテキスト

    Returns:
        現代ひらがなに変換されたテキスト
    """
    if not isinstance(text, str):
        raise TypeError("convert_hentaigana() expects a str input")
    _ensure_initialized()
    return text.translate(_TABLE or {})


def find_hentaigana(text: str) -> list[tuple[str, str, int]]:
    """
    テキスト中の変体仮名を検出する

    Args:
        text: 検査対象のテキスト

    Returns:
        (変体仮名, 現代ひらがな, 出現位置) のリスト
    """
    _ensure_initialized()
    assert _MAP is not None

    found = []
    for i, char in enumerate(text):
        if char in _MAP:
            found.append((char, _MAP[char], i))
    return found
