"""チャンク分割（G1）のテスト

text_modernizer._split_text が、句読点の乏しい戦前文書でも
全チャンクを chunk_size 以下に収め、本文後半を欠落させないことを確認する。
_split_text は Ollama 非依存の純粋関数なのでモック不要。
後半の目印のテストは、LLM への送信（_chat）だけを差し替えた子クラスで確かめる。
後半は few-shot のお手本の混入の判定と、お手本なしでの変換し直し（G14）のテスト。
末尾は訳が生成の上限で途切れたチャンクを半分に分けて変換し直す（G13）テスト。
"""

import pytest

from fakes import ScriptedChatModernizer
from utils.text_modernizer import (
    FEW_SHOT_EXAMPLES,
    SYSTEM_PROMPT,
    ChunkOverflowError,
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


# ---------- 溢れたチャンクを半分に分ける（G13） ----------
#
# 文はどれも架空のカタカナ文語（資料の本文は使わない）。

_A1 = "第一條 本令ハ陸軍ノ兵器ニ之ヲ適用ス。"
_A2 = "第二條 兵器ノ保管ハ各部隊長之ヲ掌ル。"
_TWO = _A1 + _A2


@pytest.mark.parametrize(
    "text",
    [
        _TWO,
        _A1 + _A2 + "第三條 本令ハ公布ノ日ヨリ施行ス",  # 「。」で終わらない
        "兵器ノ保管ハ各部隊長之ヲ掌リ、其ノ員數ヲ毎月報告スベシ",  # 「、」だけ
        "兵器ノ保管ハ各部隊長之ヲ掌リ其ノ員數ヲ毎月報告スベシ",  # 句読点なし
        "本令ハ陸軍ノ兵器ニ之ヲ適用ス\n兵器ノ保管ハ各部隊長之ヲ掌ル\n",  # 改行
    ],
    ids=["two-sentences", "no-final-period", "comma-only", "no-punctuation", "newlines"],
)
def test_split_in_half_adds_no_characters(text):
    """2 つに分け、つなぐと元と一字も違わない（原文に「。」などを足さない）"""
    halves = TextModernizer._split_in_half(text)

    assert len(halves) == 2
    assert all(half.strip() for half in halves)
    assert "".join(halves) == text


def test_split_in_half_cuts_after_period_near_middle():
    """真ん中にいちばん近い「。」の直後で切る"""
    assert TextModernizer._split_in_half(_TWO) == [_A1, _A2]


def test_split_in_half_prefers_period_over_comma():
    """「。」があれば「、」より優先する"""
    text = "本令ハ陸軍ノ兵器、彈藥ニ之ヲ適用ス。兵器ノ保管ハ各部隊長、各廠長之ヲ掌ル。"

    first, _ = TextModernizer._split_in_half(text)

    assert first.endswith("。")


def test_split_in_half_ignores_period_far_from_middle():
    """真ん中から大きく外れた「。」では切らない（片方が大きいままだとまた溢れる）"""
    text = "通牒ス。" + "兵器ノ保管ハ各部隊長之ヲ掌リ其ノ員數ヲ毎月報告スベシ"

    first, second = TextModernizer._split_in_half(text)

    assert first != "通牒ス。"
    assert abs(len(first) - len(second)) <= 1


def test_split_in_half_single_character_is_not_split():
    """1 字は分けられないので 1 件のまま返す"""
    assert TextModernizer._split_in_half("ス") == ["ス"]


def test_overflow_is_split_and_retried(capsys):
    """途切れた訳は採用せず、半分ずつ変換し直した訳をつなぐ。失敗には数えない

    「。」で切ったので、段落の途中に原文に無い改行は入れない。
    """
    m = ScriptedChatModernizer([("第一条 この令は陸軍の", "length"), "第一条の訳。", "第二条の訳。"])

    result = m.modernize_detailed(_TWO)

    assert result.text == "第一条の訳。第二条の訳。"
    assert "この令は陸軍の" not in result.text
    assert result.failures == []
    assert m.calls == 3
    assert [s[-1]["content"] for s in m.sent] == [_TWO, _A1, _A2]
    assert "チャンクを半分に分けて変換し直します" in capsys.readouterr().out


def test_overflow_after_split_keeps_original_chunk():
    """分けた片方がまた途切れたら、そのチャンク全体を原文のまま残し、ほかのチャンクは変換する"""
    m = ScriptedChatModernizer(
        [("途中", "length"), "第一条の訳。", ("途中", "length"), "第三条の訳。"],
        chunk_size=len(_TWO),
    )
    third = "第三條 本令ハ公布ノ日ヨリ施行ス。"

    result = m.modernize_detailed(_TWO + third)

    assert result.chunk_total == 2
    assert result.text == f"{_TWO}\n第三条の訳。"
    assert [f.index for f in result.failures] == [1]
    assert "生成の上限" in result.failures[0].message
    assert "半分に分けても収まりません" in result.failures[0].message


def test_overflow_failure_adds_no_period():
    """「。」で終わらないチャンクが分けても途切れて原文に戻るとき、「。」は付かない"""
    source = _A1 + "第二條 兵器ノ保管ハ各部隊長之ヲ掌ル"
    m = ScriptedChatModernizer([("途中", "length"), "第一条の訳。", ("途中", "length")])

    result = m.modernize_detailed(source)

    assert result.text == source
    assert not result.text.endswith("。")


def test_overflow_with_abort_raises():
    """on_chunk_error='abort' なら、分けても途切れたときに ChunkOverflowError が伝わる"""
    m = ScriptedChatModernizer([("途中", "length")], on_chunk_error="abort")

    with pytest.raises(ChunkOverflowError):
        m.modernize_detailed(_TWO)


def test_overflow_of_retry_without_examples_is_split_without_examples():
    """お手本なしで変換し直した訳が途切れたら、半分もお手本なしで送り、判定しない

    お手本つきに戻すと、混入→変換し直しを半分ごとに繰り返してしまう。
    """
    # 3 回目の訳はお手本由来の語を含むが、お手本なしの訳なので判定せずに採用する
    m = ScriptedChatModernizer(
        [_LEAK + _CLEAN, ("途中", "length"), "前半の訳。常陸", "後半の訳。"]
    )

    result = m.modernize_detailed(_TWO)

    assert result.text == "前半の訳。常陸後半の訳。"
    assert result.failures == []
    assert m.calls == 4
    assert _has_examples(m.sent[0])
    assert not any(_has_examples(sent) for sent in m.sent[1:])
    assert [sent[-1]["content"] for sent in m.sent[2:]] == [_A1, _A2]


def test_halves_are_checked_for_leak():
    """お手本つきの訳が途切れたら、半分もお手本つきで始め、混入したらお手本なしで変換し直す"""
    m = ScriptedChatModernizer([("途中", "length"), _LEAK + "前半の訳。", "前半の訳。", "後半の訳。"])

    result = m.modernize_detailed(_TWO)

    assert result.text == "前半の訳。後半の訳。"
    assert m.calls == 4
    assert _has_examples(m.sent[1])
    assert not _has_examples(m.sent[2])
    assert _has_examples(m.sent[3])
    assert m.sent[2][-1]["content"] == _A1


@pytest.mark.parametrize(
    "text",
    [_A1 + "\n" + _A2, _A1.rstrip("。") + "\n" + _A2],
    ids=["period-then-newline", "newline-only"],
)
def test_split_at_newline_keeps_one_newline(text):
    """切れ目に改行があったときは、2 つの訳を改行 1 つでつなぐ（原文の行の区切りを保つ）"""
    m = ScriptedChatModernizer([("途中", "length"), "第一条の訳。", "第二条の訳。"])

    result = m.modernize_detailed(text)

    assert result.text == "第一条の訳。\n第二条の訳。"


def test_whitespace_only_half_is_not_sent():
    """空白・改行だけの半分は LLM に送らず、そのまま残す（空の入力から文を作らせない）"""
    body = "兵器ノ保管ハ各部隊長之ヲ掌リ其ノ員數ヲ報告ス"  # 「。」なし 21 字
    text = body + "\n" * 21
    assert TextModernizer._split_in_half(text)[1].strip() == ""  # 後半が空白だけになる入力
    m = ScriptedChatModernizer([("途中", "length"), "兵器の保管は各部隊長が受け持つ。"])

    result = m.modernize_detailed(text)

    assert m.calls == 2
    assert [sent[-1]["content"] for sent in m.sent] == [text, body + "\n"]
    assert result.text.startswith("兵器の保管は各部隊長が受け持つ。")
    assert result.failures == []
