"""チャンク分割（G1）のテスト

text_modernizer._split_text が、句読点の乏しい戦前文書でも
全チャンクを chunk_size 以下に収め、本文後半を欠落させないことを確認する。
_split_text は Ollama 非依存の純粋関数なのでモック不要。
"""

from utils.text_modernizer import TextModernizer


def _modernizer(chunk_size: int) -> TextModernizer:
    """指定の chunk_size を持つ TextModernizer（LLMは呼ばない）"""
    return TextModernizer(chunk_size=chunk_size)


# ---------- 基本挙動（現状を壊さない） ----------


def test_short_text_not_split():
    """chunk_size 以下はそのまま1件で返す"""
    m = _modernizer(chunk_size=100)
    text = "我ハ日本ノ臣民ナリ。"
    assert m._split_text(text) == [text]


def test_normal_punctuated_text():
    """「。」で適切に区切れる通常文は句点境界で結合される"""
    m = _modernizer(chunk_size=12)
    # 各文8文字（「。」込み）。chunk_size=12 なら1文ずつ別チャンク。
    text = "アイウエオカキ。サシスセソタチ。"
    chunks = m._split_text(text)
    assert chunks == ["アイウエオカキ。", "サシスセソタチ。"]
    assert "".join(chunks) == text


# ---------- G1 回帰の核：句点なし長文 ----------


def test_no_period_long_text_no_loss():
    """「。」を1つも含まない長文でも、全チャンクが上限以下かつ欠落ゼロ"""
    m = _modernizer(chunk_size=50)
    # 句読点を一切含まない 200 文字（元コードでは1チャンク化して後半欠落）
    text = "ア" * 200
    chunks = m._split_text(text)

    assert len(chunks) > 1  # 分割されている
    assert all(len(c) <= 50 for c in chunks)  # 全て上限以下
    # 「。」の再付与ぶんを除けば元テキストが完全に復元できる（欠落ゼロ）
    assert "".join(chunks).replace("。", "") == text


def test_single_oversized_sentence_force_split():
    """1文（「。」の間）が単体で上限超え → 強制分割され全断片が上限以下"""
    m = _modernizer(chunk_size=30)
    # 句読点なしの1文 120 文字 + 句点
    text = "カ" * 120 + "。"
    chunks = m._split_text(text)

    assert all(len(c) <= 30 for c in chunks)
    assert "".join(chunks) == text  # 末尾の「。」も含め完全一致


# ---------- 第2段：読点・改行を優先して切る ----------


def test_prefer_comma_boundary():
    """読点「、」がある長文は、まず読点境界で分割される（自然な切れ目優先）"""
    m = _modernizer(chunk_size=20)
    # 「。」なし・「、」区切りの長文。各節は上限以下。
    text = "アイウエオカキク、サシスセソタチツ、ナニヌネノハヒフ、マミムメモヤユヨ"
    chunks = m._split_text(text)

    assert all(len(c) <= 20 for c in chunks)
    # 自然な切れ目（読点直後）で区切れているので、末尾以外の各チャンクは
    # 読点で終わる = 節の途中で機械的にぶつ切りされていない
    for c in chunks[:-1]:
        assert c.endswith("、")
    assert "".join(chunks).replace("。", "") == text


def test_split_keep_delims_helper():
    """区切り文字を手前の断片に残す小ヘルパーの単体確認"""
    result = TextModernizer._split_keep_delims("あ、い\nう", ("、", "\n"))
    assert result == ["あ、", "い\n", "う"]
    # 区切り文字なしはそのまま1件
    assert TextModernizer._split_keep_delims("あいう", ("、",)) == ["あいう"]
