"""
旧字体 → 新字体 変換エンジン

str.translate() を使ったC言語レベルの高速変換。
変換テーブルはJSONファイルから遅延ロードし、初回のみ構築してキャッシュする。

データソース:
  - joyo_old_new.json: 常用漢字の旧字体→新字体（文化庁常用漢字表準拠）
  - jinmei.json: 人名用漢字の旧字体→新字体
  - variants.json: 異体字（髙→高 等）
"""

from __future__ import annotations

import json
import threading
from importlib import resources
from typing import Mapping


# ---------- モジュールレベルキャッシュ ----------

_TABLE: Mapping[int, int] | None = None
_MAP: dict[str, str] | None = None
_INIT_LOCK = threading.Lock()


# ---------- データ読み込み ----------


def _load_json(filename: str) -> dict[str, str]:
    """data/ ディレクトリからJSONファイルを読み込む"""
    data_dir = resources.files("senzen_word.kanji") / "data"
    resource = data_dir / filename
    content = resource.read_text(encoding="utf-8")
    raw = json.loads(content)

    # 1文字→1文字のマッピングのみ保持
    return {
        k: v
        for k, v in raw.items()
        if isinstance(k, str) and isinstance(v, str) and len(k) == 1 and len(v) == 1
    }


def _load_all_tables() -> dict[str, str]:
    """全JSONファイルを読み込んで統合する"""
    merged: dict[str, str] = {}

    # 常用漢字（メインテーブル）
    merged.update(_load_json("joyo_old_new.json"))
    # 人名用漢字
    merged.update(_load_json("jinmei.json"))
    # 異体字（最後に上書きで優先）
    merged.update(_load_json("variants.json"))

    return merged


def _ensure_initialized() -> None:
    """変換テーブルを初期化する（スレッドセーフ）"""
    global _TABLE, _MAP
    if _TABLE is not None:
        return
    with _INIT_LOCK:
        if _TABLE is not None:
            return
        _MAP = _load_all_tables()
        _TABLE = {ord(k): ord(v) for k, v in _MAP.items()}


# ---------- 公開関数 ----------


def convert_old_kanji(text: str) -> str:
    """
    旧字体・異体字を新字体（現代字体）に変換する

    常用漢字表、人名用漢字、異体字の全テーブルを適用する。
    内部では str.translate() を使用しており、O(n) で高速。

    Args:
        text: 変換対象のテキスト

    Returns:
        新字体に変換されたテキスト
    """
    if not isinstance(text, str):
        raise TypeError("convert_old_kanji() expects a str input")
    _ensure_initialized()
    return text.translate(_TABLE or {})


def find_old_kanji(text: str) -> list[tuple[str, str, int]]:
    """
    テキスト中の旧字体・異体字を検出する

    Args:
        text: 検査対象のテキスト

    Returns:
        (旧字体, 新字体, 出現位置) のリスト
    """
    _ensure_initialized()
    assert _MAP is not None

    found = []
    for i, char in enumerate(text):
        if char in _MAP:
            found.append((char, _MAP[char], i))
    return found


def get_kanji_table() -> dict[str, str]:
    """
    旧字体→新字体の変換テーブル全体を辞書として返す

    Returns:
        {旧字体: 新字体, ...} の辞書
    """
    _ensure_initialized()
    assert _MAP is not None
    return dict(_MAP)
