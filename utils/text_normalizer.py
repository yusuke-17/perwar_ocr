"""
テキスト正規化モジュール

OCR出力テキストに対して、以下の正規化を一括で行う:
  1. Unicode NFKC正規化（CJK互換漢字の統一）
  2. 旧字体→新字体 + 異体字正規化（joyokanji）
  3. 半角→全角・カナ正規化（jaconv）
  4. 歴史的仮名遣い→現代仮名遣い（kana_converter）
  5. OCR誤読修正（辞書ベース + 文脈依存パターン）
  6. 空白・句読点の正規化

使い方:
    from utils.text_normalizer import normalize_text, find_normalizations

    # テキストを正規化
    result = normalize_text(raw_ocr_text)

    # 正規化対象箇所を検出（統計用）
    found = find_normalizations(raw_ocr_text)
"""

import re
import unicodedata

import jaconv
import joyokanji

from utils.kana_converter import convert_historical_kana
from utils.katakana_particle_converter import convert_katakana_particles


# ---------- OCR誤読 修正辞書 ----------
# GLM-OCRが戦前文書で誤読しやすい文字パターン
# 運用しながら追加していく

OCR_MISREAD_CORRECTIONS: dict[str, str] = {
    # 「郎」系の誤読（右側の旁が似ている）
    "郧": "郎",
    "郘": "郎",
    "郯": "郎",
    # 「術」系の誤読
    "衠": "術",
    # 「鑽」の誤読（研鑽）
    "鑜": "鑽",
    # 「翩」の誤読（翩々）
    "翤": "翩",
}


# ---------- 文脈依存の修正パターン ----------
# (正規表現パターン, 置換文字列) のリスト

CONTEXT_CORRECTIONS: list[tuple[str, str]] = [
    # カタカナに隣接する「卜」(漢字のぼく) → 「ト」(カタカナ)
    # 例: 「忽然卜シテ」→「忽然トシテ」、「コ卜」→「コト」
    (r"(?<=[ァ-ヶー])卜", "ト"),
    (r"卜(?=[ァ-ヶー])", "ト"),
]


# ---------- 正規化関数群 ----------


def _normalize_unicode(text: str) -> str:
    """Unicode NFKC正規化（CJK互換漢字の統一等）"""
    return unicodedata.normalize("NFKC", text)


def _convert_old_kanji(text: str) -> str:
    """旧字体→新字体 + 異体字の正規化（joyokanji）"""
    return joyokanji.convert(text, variants=True)


def _normalize_width(text: str) -> str:
    """半角カタカナ→全角カタカナ、全角英数字→半角英数字"""
    return jaconv.normalize(text)


def _correct_ocr_misreads(text: str) -> str:
    """OCR誤読パターンを辞書ベースで修正する"""
    for wrong, correct in OCR_MISREAD_CORRECTIONS.items():
        text = text.replace(wrong, correct)
    return text


def _correct_context_misreads(text: str) -> str:
    """文脈依存のOCR誤読を正規表現で修正する"""
    for pattern, replacement in CONTEXT_CORRECTIONS:
        text = re.sub(pattern, replacement, text)
    return text


def _normalize_punctuation(text: str) -> str:
    """句読点・記号を正規化する"""
    # 半角カンマ → 全角読点
    text = text.replace(",", "、")
    # 半角ピリオド → 全角句点（数字.数字は除外）
    text = re.sub(r"(?<!\d)\.(?!\d)", "。", text)
    # 連続する句読点を1つに
    text = re.sub(r"。{2,}", "。", text)
    text = re.sub(r"、{2,}", "、", text)
    return text


def _normalize_whitespace(text: str) -> str:
    """空白・改行を正規化する"""
    # 改行コード統一
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 各行の行頭・行末空白を除去
    lines = text.split("\n")
    lines = [line.strip() for line in lines]
    text = "\n".join(lines)
    # 3行以上の連続空行を1つの空行に圧縮
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _separate_header(text: str) -> tuple[str, str]:
    """ヘッダー行（# や --- で始まる行）と本文を分離する"""
    lines = text.split("\n")
    header = []
    body_start = 0

    for i, line in enumerate(lines):
        if line.startswith("#") or line.strip() == "---":
            header.append(line)
            body_start = i + 1
        else:
            break

    header_text = "\n".join(header)
    body_text = "\n".join(lines[body_start:])
    return header_text, body_text


# ---------- 公開関数 ----------


def normalize_text(text: str) -> str:
    """
    OCR出力テキストを正規化する（メイン関数）

    実行順序:
      1. Unicode NFKC正規化
      2. 旧字体→新字体 + 異体字（joyokanji）
      3. 半角→全角統一（jaconv）
      4. 歴史的仮名遣い→現代仮名遣い
      5. OCR誤読修正（辞書ベース + 文脈依存）
      6. カタカナ助詞→ひらがな
      7. 句読点・空白の正規化

    ヘッダー行（# で始まる行）はスキップする。

    Args:
        text: 正規化対象のテキスト

    Returns:
        正規化されたテキスト
    """
    header, body = _separate_header(text)

    if not body.strip():
        return text

    # ① Unicode正規化
    body = _normalize_unicode(body)
    # ② 旧字体→新字体
    body = _convert_old_kanji(body)
    # ③ 半角→全角
    body = _normalize_width(body)
    # ④ 歴史的仮名遣い変換
    body = convert_historical_kana(body)
    # ⑤ OCR誤読修正
    body = _correct_ocr_misreads(body)
    body = _correct_context_misreads(body)
    # ⑥ カタカナ助詞→ひらがな
    body = convert_katakana_particles(body)
    # ⑦ 句読点・空白
    body = _normalize_punctuation(body)
    body = _normalize_whitespace(body)

    if header:
        return header + "\n\n" + body
    return body


def find_normalizations(text: str) -> list[tuple[str, str, int]]:
    """
    テキスト中の正規化対象箇所を検出する（統計・デバッグ用）

    旧字体変換と仮名変換は別モジュールの find_* 関数で検出するため、
    ここではOCR誤読と文脈依存パターンのみを対象とする。

    Args:
        text: 検査対象のテキスト

    Returns:
        (変換前, 変換後, 出現位置) のリスト
    """
    found = []

    # OCR誤読辞書のチェック
    for i, char in enumerate(text):
        if char in OCR_MISREAD_CORRECTIONS:
            found.append((char, OCR_MISREAD_CORRECTIONS[char], i))

    # 文脈依存パターンのチェック
    for pattern, replacement in CONTEXT_CORRECTIONS:
        for match in re.finditer(pattern, text):
            found.append((match.group(), replacement, match.start()))

    # 位置順にソート
    found.sort(key=lambda x: x[2])
    return found
