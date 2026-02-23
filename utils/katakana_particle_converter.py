"""
カタカナ助詞 → ひらがな 変換モジュール

戦前文書ではカタカナで書かれた助詞をひらがなに変換する。
カタカナ語（外来語等）の一部を誤変換しないよう、前後の文字で判定する。

判定ルール:
  複合助詞（ニシテ, ヨリ 等）:
    - 前の文字がカタカナでない場合に変換
    - 例: 劍法ニシテ → 劍法にして（ニの前が漢字 → 変換）
    - 例: セラレタルニシテ → そのまま（ニの前がカタカナ → 変換しない）

  単一助詞（ノ, ハ 等）:
    - 前の文字がカタカナでない AND 後の文字がカタカナでない場合に変換
    - 例: 島津氏ノ武術 → 島津氏の武術（前後とも漢字 → 変換）
    - 例: 行ハレ → そのまま（後がカタカナ → 変換しない。LLMに委譲）

使い方:
    from utils.katakana_particle_converter import convert_katakana_particles

    result = convert_katakana_particles(text)
"""

import re


# ---------- 複合助詞パターン ----------
# 長い順に定義（短い部分文字列で先にマッチしないように）
# 前の文字がカタカナでない場合のみ変換する

COMPOUND_PARTICLES: list[tuple[str, str]] = [
    # 3文字以上（先に処理）
    ("ニシテ", "にして"),   # 格助詞「に」+ して
    ("トシテ", "として"),   # 格助詞「と」+ して
    # 2文字
    ("ニテ", "にて"),       # 格助詞「にて」
    ("ヨリ", "より"),       # 格助詞「より」
    ("マデ", "まで"),       # 副助詞「まで」
    ("カラ", "から"),       # 格助詞「から」
    ("ノミ", "のみ"),       # 副助詞「のみ」
    ("トモ", "とも"),       # 接続助詞「とも」
]


# ---------- 単一文字助詞 ----------

SINGLE_PARTICLES: dict[str, str] = {
    "ノ": "の",  # 格助詞（最頻出）
    "ハ": "は",  # 係助詞
    "ニ": "に",  # 格助詞
    "ヲ": "を",  # 格助詞
    "モ": "も",  # 係助詞
    "ガ": "が",  # 格助詞
    "ト": "と",  # 格助詞
    "ヘ": "へ",  # 格助詞
}


# カタカナ文字範囲（ァ-ヶ + 長音記号ー）
_KATA = r"\u30A1-\u30F6\u30FC"


# ---------- 公開関数 ----------


def convert_katakana_particles(text: str) -> str:
    """
    カタカナ助詞をひらがなに変換する

    処理順序:
      1. 複合助詞（ニシテ, ヨリ 等）を先に変換
      2. 単一文字助詞（ノ, ハ 等）を変換

    Args:
        text: 変換対象のテキスト

    Returns:
        変換後のテキスト
    """
    # Phase 1: 複合助詞（前の文字がカタカナでないとき変換）
    for kata, hira in COMPOUND_PARTICLES:
        pattern = rf"(?<![{_KATA}]){re.escape(kata)}"
        text = re.sub(pattern, hira, text)

    # Phase 2: 単一文字助詞（前後ともカタカナでないとき変換）
    for kata, hira in SINGLE_PARTICLES.items():
        pattern = rf"(?<![{_KATA}]){re.escape(kata)}(?![{_KATA}])"
        text = re.sub(pattern, hira, text)

    return text


def find_katakana_particles(text: str) -> list[tuple[str, str, int]]:
    """
    テキスト中のカタカナ助詞を検出する（統計用）

    Args:
        text: 検査対象のテキスト

    Returns:
        (カタカナ, ひらがな, 出現位置) のリスト
    """
    found = []

    # 複合助詞
    for kata, hira in COMPOUND_PARTICLES:
        pattern = rf"(?<![{_KATA}]){re.escape(kata)}"
        for match in re.finditer(pattern, text):
            found.append((kata, hira, match.start()))

    # 単一文字助詞
    for kata, hira in SINGLE_PARTICLES.items():
        pattern = rf"(?<![{_KATA}]){re.escape(kata)}(?![{_KATA}])"
        for match in re.finditer(pattern, text):
            found.append((kata, hira, match.start()))

    found.sort(key=lambda x: x[2])
    return found
