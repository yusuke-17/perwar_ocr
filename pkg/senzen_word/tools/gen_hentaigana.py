"""変体仮名変換テーブル（hentaigana.json）の生成スクリプト

開発用ツール。パッケージ本体（src/）には含めない。

Unicode の正式な文字名から機械的に変換表を作る。手作業でコードポイントと音を
対応づけると必ずズレるため（実際、初版は260件中257件が誤りだった）、
唯一の正解を Python 標準の `unicodedata` に委ねる。

命名規則:
    U+1B002〜U+1B11E の変体仮名は、すべて
        HENTAIGANA LETTER <ROMAJI>-<識別子>
    という名前を持つ。最初のハイフンより前が字母の音。

    例) HENTAIGANA LETTER A-1      → A  → あ
        HENTAIGANA LETTER KA-KE    → KA → か
        HENTAIGANA LETTER N-MU-MO-1→ N  → ん

    識別子が数字でないものが11字ある（A-WO / KA-KE / KO-KI / TU-TO / TO-RA /
    NI-TE / NE-KO / ME-MA / YA-YO / N-MU-MO-1 / N-MU-MO-2）。これらは
    「その字が複数の音に読まれうる」ことを示すが、本テーブルは先頭の音を採る。
    とくに N-MU-MO は「ん・む・も」のいずれにも読めるが「ん」に寄せる。

使い方:
    uv run python pkg/senzen_word/tools/gen_hentaigana.py

    生成結果は src/senzen_word/kana/data/hentaigana.json に上書きされる。
    正しさは tests/test_hentaigana.py の test_table_matches_unicode_names が
    同じ規則で再導出して検証する。
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path


# 変体仮名ブロックの範囲（Unicode 10.0 で追加）
#   Kana Supplement:  U+1B002〜U+1B0FF
#   Kana Extended-A:  U+1B100〜U+1B11E
CODEPOINT_START = 0x1B002
CODEPOINT_END = 0x1B11E

NAME_PREFIX = "HENTAIGANA LETTER "

# 字母の音（ローマ字）→ 現代ひらがな
ROMAJI_TO_HIRAGANA: dict[str, str] = {
    "A": "あ", "I": "い", "U": "う", "E": "え", "O": "お",
    "KA": "か", "KI": "き", "KU": "く", "KE": "け", "KO": "こ",
    "SA": "さ", "SI": "し", "SU": "す", "SE": "せ", "SO": "そ",
    "TA": "た", "TI": "ち", "TU": "つ", "TE": "て", "TO": "と",
    "NA": "な", "NI": "に", "NU": "ぬ", "NE": "ね", "NO": "の",
    "HA": "は", "HI": "ひ", "HU": "ふ", "HE": "へ", "HO": "ほ",
    "MA": "ま", "MI": "み", "MU": "む", "ME": "め", "MO": "も",
    "YA": "や", "YU": "ゆ", "YO": "よ",
    "RA": "ら", "RI": "り", "RU": "る", "RE": "れ", "RO": "ろ",
    "WA": "わ", "WI": "ゐ", "WE": "ゑ", "WO": "を",
    "N": "ん",
}

OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "src" / "senzen_word" / "kana" / "data" / "hentaigana.json"
)


def hiragana_for(name: str) -> str:
    """変体仮名の Unicode 名から対応する現代ひらがなを求める

    Args:
        name: 例 "HENTAIGANA LETTER KA-KE"

    Returns:
        対応する現代ひらがな（例 "か"）

    Raises:
        ValueError: 未知の字母音が現れた場合（Unicode 側の追加を検知する）
    """
    romaji = name[len(NAME_PREFIX):].split("-")[0]
    if romaji not in ROMAJI_TO_HIRAGANA:
        raise ValueError(f"未知の字母音です: {romaji}（{name}）")
    return ROMAJI_TO_HIRAGANA[romaji]


def build_table() -> dict[str, str]:
    """変体仮名 → 現代ひらがな の変換表を作る"""
    table: dict[str, str] = {}

    for codepoint in range(CODEPOINT_START, CODEPOINT_END + 1):
        char = chr(codepoint)
        try:
            name = unicodedata.name(char)
        except ValueError:
            # 未割り当てのコードポイント
            continue
        if not name.startswith(NAME_PREFIX):
            # 同じ範囲にある archaic 仮名（U+1B11F 等）は対象外
            continue
        table[char] = hiragana_for(name)

    return table


def main() -> None:
    table = build_table()

    OUTPUT_PATH.write_text(
        json.dumps(table, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"生成しました: {OUTPUT_PATH}")
    print(f"  文字数: {len(table)}")
    print(f"  Unicodeバージョン: {unicodedata.unidata_version}")


if __name__ == "__main__":
    main()
