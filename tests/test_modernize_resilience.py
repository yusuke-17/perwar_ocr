"""口語体変換の失敗耐性（G2b/G2c）のテスト

1チャンクの失敗で成功済みチャンクを捨てないこと、
失敗チャンクが原文のまま残って文字が欠けないことを確認する。
LLM呼び出し部（_modernize_chunk）だけを差し替えたサブクラスで検証するため、
Ollama もモックライブラリも不要。
"""

import pytest

from utils.ollama_client import OllamaTimeoutError
from utils.text_modernizer import FewShotLeakError, ModernizeResult, TextModernizer


class _StubModernizer(TextModernizer):
    """_modernize_chunk を差し替えた TextModernizer

    fail_at: 失敗させるチャンク番号（1始まり）→ 投げる例外
    """

    def __init__(self, fail_at: dict[int, BaseException] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.fail_at = fail_at or {}
        self.calls = 0

    def _check_model_available(self) -> None:
        """モデル存在確認はテストでは不要なので無効化する"""

    def _modernize_chunk(self, chunk: str) -> str:
        self.calls += 1
        error = self.fail_at.get(self.calls)
        if error is not None:
            raise error
        return f"[変換済み]{chunk}"


def _text(sentences: int, chunk_size: int = 10) -> str:
    """chunk_size ちょうどで分かれる、区別できる文を並べたテキスト"""
    return "".join(f"文{i}アイウエオカキ。" for i in range(1, sentences + 1))


# ---------- チャンク単位の失敗吸収 ----------


def test_failed_chunk_keeps_original_text():
    """失敗チャンクは原文のまま残り、他チャンクの変換結果は保持される"""
    m = _StubModernizer(fail_at={3: RuntimeError("500 error")}, chunk_size=10)
    text = _text(5)

    result = m.modernize_detailed(text)

    assert isinstance(result, ModernizeResult)
    assert result.chunk_total == 5
    assert len(result.failures) == 1
    assert result.failures[0].index == 3
    # 3番目の原文がそのまま残り、他は変換されている
    assert "文3アイウエオカキ。" in result.text
    assert result.text.count("[変換済み]") == 4
    assert m.calls == 5  # 失敗しても最後まで処理する


def test_all_chunks_fail_returns_original():
    """全チャンク失敗でも例外を投げず、原文をそのまま返す"""
    m = _StubModernizer(
        fail_at={i: RuntimeError("落ちました") for i in range(1, 6)}, chunk_size=10
    )
    text = _text(5)

    result = m.modernize_detailed(text)

    assert len(result.failures) == 5
    assert "[変換済み]" not in result.text
    for i in range(1, 6):
        assert f"文{i}アイウエオカキ。" in result.text


def test_no_character_loss_on_failure():
    """失敗しても本文の文字が欠けない（G1と同じ「文字を消さない」保証）"""
    m = _StubModernizer(fail_at={2: RuntimeError("失敗")}, chunk_size=10)
    text = _text(4)

    result = m.modernize_detailed(text)

    stripped = result.text.replace("[変換済み]", "").replace("\n", "")
    assert stripped == text


def test_timed_out_chunk_keeps_original_text():
    """タイムアウトしたチャンクも原文のまま残り、後続は処理される（G4）

    従来はここで無限ハングしていた。例外になったことで keep_original の
    仕組みに乗り、変換済みの分も失われない。
    """
    m = _StubModernizer(
        fail_at={2: OllamaTimeoutError("300 秒以内に応答しませんでした")},
        chunk_size=10,
    )
    text = _text(4)

    result = m.modernize_detailed(text)

    assert len(result.failures) == 1
    assert result.failures[0].index == 2
    assert "文2アイウエオカキ。" in result.text
    assert result.text.count("[変換済み]") == 3
    assert m.calls == 4


def test_on_chunk_error_abort_raises():
    """on_chunk_error='abort' なら従来どおり例外を送出する"""
    m = _StubModernizer(
        fail_at={2: RuntimeError("失敗")}, chunk_size=10, on_chunk_error="abort"
    )

    try:
        m.modernize_detailed(_text(4))
    except RuntimeError:
        pass
    else:
        raise AssertionError("abort 指定なのに例外が送出されなかった")


# ---------- 中断（Ctrl+C） ----------


def test_keyboard_interrupt_keeps_processed_and_rest():
    """Ctrl+C 時は変換済み分を保持し、残りは原文のまま返す（後半を欠落させない）"""
    m = _StubModernizer(fail_at={3: KeyboardInterrupt()}, chunk_size=10)
    text = _text(5)

    result = m.modernize_detailed(text)

    assert result.aborted is True
    assert result.failures == []
    assert result.text.count("[変換済み]") == 2  # 1,2チャンク目のみ変換済み
    assert m.calls == 3  # 4チャンク目以降は呼ばない
    stripped = result.text.replace("[変換済み]", "").replace("\n", "")
    assert stripped == text


# ---------- 後方互換 ----------


def test_modernize_returns_str():
    """modernize() は従来どおり str を返す（既存の呼び出しが壊れない）"""
    m = _StubModernizer(chunk_size=10)

    out = m.modernize(_text(3))

    assert isinstance(out, str)
    assert out.count("[変換済み]") == 3


def test_header_is_preserved():
    """# で始まるヘッダー行は変換せずそのまま残る（既存挙動の維持）"""
    m = _StubModernizer(chunk_size=100)

    result = m.modernize_detailed("# タイトル\n本文アイウ。")

    assert result.text.startswith("# タイトル")
    assert "[変換済み]" in result.text


def test_empty_body_returns_as_is():
    """本文が空ならLLMを呼ばずそのまま返す"""
    m = _StubModernizer(chunk_size=100)

    result = m.modernize_detailed("# タイトルのみ\n")

    assert result.chunk_total == 0
    assert result.failures == []
    assert result.aborted is False
    assert m.calls == 0


# ---------- お手本の混入が続くチャンク（G14） ----------

_S1 = "第一條 陸軍省ハ左記ノ通リ通牒ス。"
_S2 = "第二條 當分ノ間從前ノ例ニ依ル。"
_S3 = "第三條 本令ハ公布ノ日ヨリ施行ス。"
_LEAK = "思うに、皇室の祖先が国を開いたのは遥か昔のことだった。"


class _LeakingModernizer(TextModernizer):
    """_chat を差し替え、leak_in を含むチャンクにだけお手本の混入を返す

    お手本の有無にかかわらず同じ応答を返す。

    interrupt_on_call: その回数目の呼び出しで KeyboardInterrupt を投げる
    """

    def __init__(self, leak_in: str, interrupt_on_call: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.leak_in = leak_in
        self.interrupt_on_call = interrupt_on_call
        self.calls = 0

    def _check_model_available(self) -> None:
        """モデル存在確認はテストでは不要なので無効化する"""

    def _chat(self, messages):
        self.calls += 1
        if self.calls == self.interrupt_on_call:
            raise KeyboardInterrupt
        chunk = messages[-1]["content"]
        if self.leak_in in chunk:
            return _LEAK + "[変換済み]" + chunk
        return "[変換済み]" + chunk


def test_leak_without_retry_keeps_original_chunk():
    """お手本なしで変換し直さない設定では、混入した断片は旧字体・カタカナの原文のまま残り、ほかは変換される"""
    m = _LeakingModernizer(leak_in="第二條", chunk_size=20, retry_without_examples=False)

    result = m.modernize_detailed(_S1 + _S2 + _S3)

    assert result.chunk_total == 3
    assert result.text == f"[変換済み]{_S1}\n{_S2}\n[変換済み]{_S3}"
    assert "皇室の祖先" not in result.text
    assert [f.index for f in result.failures] == [2]
    assert "お手本の例文が混入" in result.failures[0].message
    assert m.calls == 3


def test_leak_without_retry_and_abort_raises():
    """on_chunk_error='abort' なら混入を見つけた時点で FewShotLeakError が伝わる"""
    m = _LeakingModernizer(
        leak_in="第二條",
        chunk_size=20,
        retry_without_examples=False,
        on_chunk_error="abort",
    )

    with pytest.raises(FewShotLeakError):
        m.modernize_detailed(_S1 + _S2 + _S3)


def test_keyboard_interrupt_during_retry_keeps_rest():
    """お手本なしの変換し直しの途中の Ctrl+C は既存の中断処理に届き、残りは原文のまま残る"""
    # 1 回目: 第一條、2 回目: 第二條（混入）、3 回目: 第二條のお手本なしの変換で中断
    m = _LeakingModernizer(leak_in="第二條", interrupt_on_call=3, chunk_size=20)

    result = m.modernize_detailed(_S1 + _S2 + _S3)

    assert result.aborted is True
    assert result.text == f"[変換済み]{_S1}\n{_S2}\n{_S3}"
    assert result.failures == []
