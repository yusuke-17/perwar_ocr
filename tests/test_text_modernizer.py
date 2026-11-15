"""チャンク分割（G1）のテスト

text_modernizer._split_text が、句読点の乏しい戦前文書でも
全チャンクを chunk_size 以下に収め、本文後半を欠落させないことを確認する。
_split_text は Ollama 非依存の純粋関数なのでモック不要。
後半の目印のテストは、LLM への送信（_chat）だけを差し替えた子クラスで確かめる。
末尾は few-shot のお手本の混入の判定と、お手本なしでの変換し直し（G14）のテスト。
"""

import pytest

from fakes import ScriptedChatModernizer
from utils.text_modernizer import (
    FEW_SHOT_EXAMPLES,
    SYSTEM_PROMPT,
    FewShotLeakError,
    TextModernizer,
    find_few_shot_leak,
)


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
    # つなぐと元テキストと完全一致（欠落ゼロ・原文に無い「。」も付かない）
    assert "".join(chunks) == text


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
    assert "".join(chunks) == text


def test_split_keep_delims_helper():
    """区切り文字を手前の断片に残す小ヘルパーの単体確認"""
    result = TextModernizer._split_keep_delims("あ、い\nう", ("、", "\n"))
    assert result == ["あ、", "い\n", "う"]
    # 区切り文字なしはそのまま1件
    assert TextModernizer._split_keep_delims("あいう", ("、",)) == ["あいう"]


# ---------- 原文に無い字を足さない（B3） ----------


def test_long_text_not_ending_with_period_gets_no_extra_period():
    """「。」で終わらない長文の最後の断片に「。」が付かない"""
    m = _modernizer(chunk_size=20)
    text = "第一條 本法ハ公布ノ日ヨリ之ヲ施行ス。" + "附則 當分ノ間從前ノ例ニ依ル" * 3
    chunks = m._split_text(text)

    assert len(chunks) > 1
    assert not chunks[-1].endswith("。")
    assert "".join(chunks) == text


def test_chunks_always_rejoin_to_original():
    """どんな入力でも、チャンクをつなぐと分割前の文と一字も違わない"""
    samples = [
        "壹。貳。參",
        "。。。前置キ\n\n本文ノ途中\n續キ。\n\n",
        "\n\n" + "ア" * 70 + "。\n" + "イ、" * 30 + "\nウ" * 10,
        "我ハ日本ノ臣民ナリ。" * 9 + "  \n",
    ]
    for size in (5, 13, 30):
        m = _modernizer(chunk_size=size)
        for text in samples:
            chunks = m._split_text(text)
            assert "".join(chunks) == text, (size, text)
            assert all(len(c) <= size for c in chunks), (size, text)


# ---------- 目印の行を変換しない（G11） ----------
#
# LLM への送信（_chat）とモデル確認だけを差し替えた子クラスで、
# 実際に LLM に渡る断片を受け取って確かめる。

_GAP = "〔第2頁 読み取り失敗（IMG_0002.png）〕"


class _RecordingModernizer(TextModernizer):
    """LLM に渡したメッセージを記録し、「[変換済み]断片」を返す

    fail_at: 失敗させる呼び出し番号（1始まり）→ 投げる例外
    """

    def __init__(self, fail_at: dict[int, BaseException] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.fail_at = fail_at or {}
        self.sent: list[list[dict[str, str]]] = []

    def _check_model_available(self) -> None:
        """モデル存在確認はテストでは不要なので無効化する"""

    def _chat(self, messages):
        self.sent.append(messages)
        error = self.fail_at.get(len(self.sent))
        if error is not None:
            raise error
        return f"[変換済み]{messages[-1]['content'].strip()}"

    @property
    def chunks(self) -> list[str]:
        """LLM に渡した断片（各メッセージの最後の user の内容）"""
        return [messages[-1]["content"] for messages in self.sent]


def test_marker_is_not_sent_and_kept_in_place():
    """目印の前後は別々の呼び出しで変換され、目印はそのまま同じ位置に残る"""
    m = _RecordingModernizer(chunk_size=2000)
    text = f"陸軍省ノ當分ノ間\n\n{_GAP}\n\n施行スルコトヲ得"

    result = m.modernize_detailed(text)

    assert m.chunks == ["陸軍省ノ當分ノ間", "施行スルコトヲ得"]
    assert all(_GAP not in c for c in m.chunks)
    assert result.text == f"[変換済み]陸軍省ノ當分ノ間\n\n{_GAP}\n\n[変換済み]施行スルコトヲ得"
    assert result.chunk_total == 2


def test_fix_input_with_markers_never_spans_marker():
    """prewar fix 相当: 目印を含む OCR 生テキストを長い区間ごとに分割しても、目印をまたがない"""
    m = _RecordingModernizer(chunk_size=20)
    before = "第一條 本法ハ公布ノ日ヨリ施行ス。" * 3
    after = "附則 當分ノ間從前ノ例ニ依ル。" * 3
    text = f"{before}\n\n{_GAP}\n\n〔第3〜4頁 未処理〕\n\n{after}"

    result = m.modernize_detailed(text)

    assert "".join(c for c in m.chunks if "第一條" in c or "施行ス" in c) == before
    assert all(not (("施行ス" in c) and ("附則" in c)) for c in m.chunks)
    assert f"\n\n{_GAP}\n\n〔第3〜4頁 未処理〕\n\n" in result.text
    assert result.chunk_total == len(m.chunks)


def test_marker_only_text_does_not_call_llm():
    m = _RecordingModernizer()
    text = f"{_GAP}\n\n〔第3〜4頁 未処理〕"

    result = m.modernize_detailed(text)

    assert m.sent == []
    assert result.text == text
    assert result.chunk_total == 0


def test_failure_after_marker_is_numbered_and_kept_as_original():
    """目印の後ろの区間の失敗は、LLM に渡した順の番号で記録され、その区間は原文のまま残る"""
    m = _RecordingModernizer(fail_at={2: RuntimeError("500 error")})
    text = f"前ノ本文\n\n{_GAP}\n\n後ノ本文ハ句点ナク續ク"

    result = m.modernize_detailed(text)

    assert [f.index for f in result.failures] == [2]
    assert result.text == f"[変換済み]前ノ本文\n\n{_GAP}\n\n後ノ本文ハ句点ナク續ク"
    assert not result.text.endswith("。")


def test_failed_last_chunk_gets_no_extra_period():
    """「。」で終わらない長文の最後の断片が失敗しても、原文に無い「。」は付かない"""
    m = _RecordingModernizer(chunk_size=20)
    text = "第一條 本法ハ公布ノ日ヨリ施行ス。" + "附則 當分ノ間從前ノ例ニ依ル" * 3
    m.fail_at = {len(m._split_text(text)): RuntimeError("500 error")}

    result = m.modernize_detailed(text)

    assert len(result.failures) == 1
    # 最後の断片（文字数で切られた「依ル」）が原文のまま残り、「。」は付かない
    assert result.text.endswith("\n依ル")


# ---------- お手本の混入の判定（G14） ----------

# お手本と無関係なカタカナ文語の原文
_UNRELATED = "陸軍省ハ左記ノ通リ通牒ス。"


def test_build_messages_uses_only_input_and_output():
    """目印を足してもプロンプトは変わらない（input / output だけを使う）"""
    messages = TextModernizer._build_messages("本文")

    expected = [{"role": "system", "content": SYSTEM_PROMPT}]
    for example in FEW_SHOT_EXAMPLES:
        expected.append({"role": "user", "content": example["input"]})
        expected.append({"role": "assistant", "content": example["output"]})
    expected.append({"role": "user", "content": "本文"})
    assert messages == expected


def test_actual_leak_from_2026_11_03_is_detected():
    """B3 の実機確認で実際に混入した文（お手本の訳し直し）を混入と判定する"""
    result = "その流派の開祖は常陸国の出身で、はじめは心影流を学んだ。陸軍省は次のとおり通知する。"

    marker = find_few_shot_leak(_UNRELATED, result)

    assert marker is not None
    assert "常陸" in marker.output_terms


def test_quoted_source_is_not_leak():
    """原文が実際に引用しているなら混入とみなさない"""
    source = "其ノ流祖ハ常陸國ノ人ニシテ、始メ心影流ヲ學ビタリ。"
    result = "その流派の創始者は常陸国の出身で、はじめは心影流を学んだ。"

    assert find_few_shot_leak(source, result) is None


def test_one_general_phrase_alone_is_not_leak():
    """租税の文書で「税金を納める義務」だけが出ても混入とみなさない"""
    source = "租税ヲ納ムルハ國民ノ義務ナリ。"
    result = "税金を納める義務は国民にある。"

    assert find_few_shot_leak(source, result) is None


def test_both_general_phrases_are_leak():
    """「日本の国民は」と「税金を納める義務」がそろい、原文に臣民・納税が無ければ混入"""
    result = "日本の国民は、法律に従って税金を納める義務がある。陸軍省は通知する。"

    assert find_few_shot_leak(_UNRELATED, result) is not None


def test_old_form_tax_in_source_is_not_leak():
    """正規化していない原文の「納稅」（旧字体）も本物の引用とみなす"""
    source = "日本臣民ハ法律ノ定ムル所ニ從ヒ納稅ノ義務ヲ有ス。"
    result = "日本の国民は、法律の定めに従って税金を納める義務がある。"

    assert find_few_shot_leak(source, result) is None


def test_clean_result_is_not_leak():
    assert find_few_shot_leak(_UNRELATED, "陸軍省は次のとおり通知する。") is None


@pytest.mark.parametrize(
    "example", FEW_SHOT_EXAMPLES, ids=[f"例{i + 1}" for i in range(len(FEW_SHOT_EXAMPLES))]
)
def test_every_example_has_working_markers(example):
    """お手本ごとに目印があり、出力は混入と判定され、入力が原文なら見逃す（design D4）"""
    assert example["leak_markers"], "お手本に目印の組が無い"
    assert find_few_shot_leak(_UNRELATED, example["output"]) is not None
    assert find_few_shot_leak(example["input"], example["output"]) is None


# ---------- 混入したらお手本なしで変換し直す（G14） ----------

_LEAK = "その流派の開祖は常陸国の出身で、はじめは心影流を学んだ。"
_CLEAN = "陸軍省は次のとおり通知する。"


def _has_examples(messages) -> bool:
    return any(m["role"] == "assistant" for m in messages)


def test_leak_retries_once_without_examples(capsys):
    """お手本つきの結果に混入 → お手本なしで 1 回変換し直した結果を採用し、失敗には数えない"""
    m = ScriptedChatModernizer([_LEAK + _CLEAN, _CLEAN])

    result = m.modernize_detailed(_UNRELATED)

    assert result.text == _CLEAN
    assert "常陸国" not in result.text
    assert result.failures == []
    assert m.calls == 2
    assert _has_examples(m.sent[0])
    assert m.sent[1] == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _UNRELATED},
    ]
    out = capsys.readouterr().out
    assert "お手本の例文の混入を検出（常陸）。お手本なしで変換し直します" in out


def test_result_without_examples_is_adopted_without_check():
    """お手本なしの結果は判定せずに採用する（引用がチャンクの境目で切れた場合の誤判定で訳を捨てない）"""
    # 「朕惟フニ我ガ皇祖」までが前のチャンクにあり、このチャンクに「皇祖」が無い
    source = "國ヲ肇ムルコト宏遠ニ德ヲ樹ツルコト深厚ナリ。"
    translated = "皇室の祖先が国を開いたのは遥か昔のことで、その徳は深く厚い。"
    m = ScriptedChatModernizer([translated])

    result = m.modernize_detailed(source)

    assert m.calls == 2
    assert result.text == translated
    assert result.failures == []


def test_clean_chunk_is_sent_with_examples_once():
    """混入が無いチャンクは今までどおりお手本つきで 1 回だけ変換する"""
    m = ScriptedChatModernizer([_CLEAN])

    m.modernize_detailed(_UNRELATED)

    assert m.sent == [TextModernizer._build_messages(_UNRELATED)]


def test_retry_disabled_keeps_original():
    """retry_without_examples=False なら変換し直さず、原文のまま残して失敗に数える"""
    m = ScriptedChatModernizer([_LEAK + _CLEAN], retry_without_examples=False)

    result = m.modernize_detailed(_UNRELATED)

    assert m.calls == 1
    assert result.text == _UNRELATED
    assert len(result.failures) == 1
    assert "お手本の例文が混入しました（常陸）" in result.failures[0].message


def test_tax_document_with_kokumin_is_not_leak():
    """「國民」と「租税」で書かれた本物の租税の文は、訳に両方の言い回しが出ても混入としない"""
    source = "日本國民ハ租税ヲ納ムルノ義務ヲ負フ。"
    result = "日本の国民は、税金を納める義務を負う。"

    assert find_few_shot_leak(source, result) is None


@pytest.mark.parametrize("source", ["我ガ祖宗ノ遺訓ニ從ヒ", "皇宗ノ遺訓ヲ奉ジ", "列聖ノ遺訓ニ從ヒ"])
def test_imperial_ancestors_in_other_words_is_not_leak(source):
    """「皇室の祖先」は祖宗・皇宗・列聖の訳にもなるので、原文にあれば混入としない"""
    assert find_few_shot_leak(source, "皇室の祖先の教えに従い") is None
