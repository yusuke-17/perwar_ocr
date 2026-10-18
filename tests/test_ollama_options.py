"""OCRの生成パラメータとタイムアウト（G4）のテスト

Ollamaは起動していなくてよい。ollama.Client の生成は通信を伴わず、
例外の翻訳は ollama_errors に閉じているため、どちらも実物のまま検証できる。
"""

import cv2
import httpx
import numpy as np
import ollama
import pytest

from utils import ollama_client
from utils.ollama_client import (
    OllamaConnectionError,
    OllamaModelNotFoundError,
    OllamaOCRClient,
    OllamaRepeatError,
    OllamaTimeoutError,
    chat_client,
    generate_timeout,
    list_client,
    list_timeout,
    ocr_options,
    ocr_retry_count,
    ollama_errors,
    ollama_version,
    trim_repetition,
)


class _FakeConfig:
    """CONFIG.get だけを差し替える最小のフェイク

    utils.config.Config と同じドット記法のインターフェースを持つ。
    """

    def __init__(self, values: dict):
        self._values = values

    def get(self, dotted_key, default=None):
        return self._values.get(dotted_key, default)


# ---------- OCRの生成パラメータ ----------


def test_ocr_options_is_deterministic():
    """OCRは temperature=0 / seed 固定で走る（同じ画像なら同じ結果）"""
    opts = ocr_options()

    assert opts["temperature"] == 0.0
    assert opts["seed"] == 0


def test_ocr_options_returns_a_copy():
    """戻り値を書き換えてもグローバル設定が汚れない"""
    opts = ocr_options()
    opts["temperature"] = 9.9

    assert ocr_options()["temperature"] == 0.0


def test_num_predict_is_capped_by_default():
    """G12: 既定で生成トークン数の上限 1024 が渡る（反復で 1 枚 55 秒かけない）"""
    assert ocr_options()["num_predict"] == 1024


@pytest.mark.parametrize("value", [0, -1])
def test_zero_num_predict_means_unlimited(monkeypatch, value):
    """0 以下なら num_predict を渡さない＝無制限（従来の挙動に戻す退避口）"""
    monkeypatch.setattr(
        ollama_client,
        "CONFIG",
        _FakeConfig({"ocr": {"temperature": 0.0, "num_predict": value}}),
    )

    assert "num_predict" not in ocr_options()


def test_retry_on_repeat_is_not_an_ollama_option():
    """retry_on_repeat は生成パラメータではないので options に混ぜない。既定は 0 回"""
    assert "retry_on_repeat" not in ocr_options()
    assert ocr_retry_count() == 0


def test_negative_retry_count_means_no_retry(monkeypatch):
    """retry_on_repeat が負でも 0 回（再試行しない）として扱う"""
    monkeypatch.setattr(
        ollama_client, "CONFIG", _FakeConfig({"ocr.retry_on_repeat": -3})
    )

    assert ocr_retry_count() == 0


# ---------- 反復の切り落とし ----------

_HEADING = "陸軍省送達"
_BODY = ["一、本件ハ別紙ノ通リ", "二、經費ハ追テ通牒ス", "三、右ニ依リ處理スヘシ",
         "四、期日ハ十月十日トス", "五、以上"]


@pytest.mark.parametrize(
    "text, expected_text",
    [
        # 反復あり: 見出し＋本文5行のあとに同じ本文5行を何度も繰り返す → 最初の5行だけ残る
        (
            "\n".join([_HEADING, *_BODY, *_BODY, *_BODY, *_BODY[:2]]),
            "\n".join([_HEADING, *_BODY]),
        ),
        # 反復なし: 一文字も変えない（末尾の空白・空行もそのまま）
        ("\n".join([_HEADING, *_BODY]) + "\n\n", "\n".join([_HEADING, *_BODY]) + "\n\n"),
        # 空行は反復と見なさない
        (
            "\n".join([_HEADING, "", _BODY[0], "", "", _BODY[1], "   "]),
            "\n".join([_HEADING, "", _BODY[0], "", "", _BODY[1], "   "]),
        ),
        # 正当な繰り返し（「同上」）でも 2 回目以降は切られる（仕様で明示した割り切り）
        (
            "\n".join(["一、歩兵 第一聯隊", "同上", "二、騎兵 第一聯隊", "同上", "三、砲兵"]),
            "\n".join(["一、歩兵 第一聯隊", "同上", "二、騎兵 第一聯隊"]),
        ),
    ],
    ids=["repeated", "no-repetition", "blank-lines", "legit-repeat"],
)
def test_trim_repetition(text, expected_text):
    """仕様「OCR 出力の反復の切り落とし」の4シナリオ"""
    trimmed_text, trimmed_chars = trim_repetition(text)

    assert trimmed_text == expected_text
    assert trimmed_chars == len(text) - len(expected_text)


# 旧字体・カタカナ書きの本文（30字以上、架空の例文）。glm-ocr はこれを1字だけ読み違えて繰り返す
_LONG = "明治ノ末ヨリ各地ニ學校ノ設立相次ギ、教育ノ普及大ニ發達シ、其ノ成果見ルベキモノ頗ル多シ"


def test_trim_repetition_catches_one_char_variant():
    """仕様「1 文字違いで繰り返す行も切り落とされる」（実機 3.png の 橃→橝 の形）"""
    variant = _LONG.replace("發", "癹")
    assert variant != _LONG
    kept = f"{_HEADING}\n\n{_LONG}"
    text = f"{kept}\n\n\n{variant}\n\n{_LONG[:20]}"

    assert trim_repetition(text) == (kept, len(text) - len(kept))


def test_trim_repetition_catches_inline_loop():
    """仕様「改行の無い行の中の反復も切り落とされる」（実機 8.png の形）"""
    loop = "右ノ件ニ關シ縣下各郡ヘ通牒シ、速ニ調査ノ上報告セシムベシ、尚又、"
    # 句の直前は句の末尾（、）と違う字にする（同じだと反復の始まりが1字前にずれる）
    head = "第三號通牒\n\n本月十日附ヲ以テ" + loop
    text = head + loop * 5 + loop[:10]

    assert trim_repetition(text) == (head, len(text) - len(head))


def test_trim_repetition_keeps_short_table_rows():
    """仕様「1 文字違いの短い行が並ぶ表は切り落とさない」"""
    rows = [f"第{n}中隊　兵員百二十名　馬匹十二頭" for n in "一二三四五"]
    text = "\n".join(["編成表", *rows])

    assert trim_repetition(text) == (text, 0)


def test_trim_repetition_keeps_rules_and_runs_of_one_char():
    """罫線や同じ字の連続は「行の中の反復」と見なさない"""
    text = "\n".join([_HEADING, "―" * 60, "以下余白" + "。" * 50, _BODY[0]])

    assert trim_repetition(text) == (text, 0)


def test_trim_repetition_ignores_surrounding_spaces():
    """前後の空白だけが違う行も同じ行と見なす"""
    kept = f"{_BODY[0]}\n{_BODY[1]}"
    text = f"{kept}\n  {_BODY[0]} \n"

    assert trim_repetition(text) == (kept, len(text) - len(kept))


# ---------- タイムアウトの配線 ----------


def test_timeout_reaches_httpx():
    """configのtimeoutが実際にhttpxのクライアントまで届いているか

    ここだけ ollama.Client の私有属性を覗く。configの値が本当に効くかは
    この経路でしか確認できないため（Client生成自体は通信しない）。
    """
    assert chat_client()._client.timeout.read == 300.0
    assert list_client()._client.timeout.read == 15.0


def test_zero_timeout_means_unlimited(monkeypatch):
    """0を指定すると無制限（従来の挙動）に戻せる＝退避口が生きている"""
    monkeypatch.setattr(
        ollama_client,
        "CONFIG",
        _FakeConfig(
            {"ollama.generate_timeout_seconds": 0, "ollama.list_timeout_seconds": -1}
        ),
    )

    assert generate_timeout() is None
    assert list_timeout() is None


def test_timeout_is_read_at_call_time(monkeypatch):
    """import時に焼き込まず毎回configを読む（設定差し替えが効く）"""
    monkeypatch.setattr(
        ollama_client,
        "CONFIG",
        _FakeConfig({"ollama.generate_timeout_seconds": 42}),
    )

    assert generate_timeout() == 42.0


# ---------- 例外の翻訳 ----------


@pytest.mark.parametrize(
    "raised, expected",
    [
        (httpx.ReadTimeout("timed out"), OllamaTimeoutError),
        (httpx.ConnectTimeout("timed out"), OllamaTimeoutError),
        (httpx.WriteTimeout("timed out"), OllamaTimeoutError),
        (ConnectionError("refused"), OllamaConnectionError),
        (ollama.ResponseError("model 'x' not found", 404), OllamaModelNotFoundError),
        (
            ollama.ResponseError(
                '{"error":"prediction aborted, token repeat limit reached"}', 500
            ),
            OllamaRepeatError,
        ),
    ],
)
def test_error_translation(raised, expected):
    """Ollama由来の例外がPJ共通の例外に翻訳される"""
    with pytest.raises(expected):
        with ollama_errors("glm-ocr", 300):
            raise raised


def test_timeout_message_tells_how_to_extend():
    """タイムアウトのメッセージに秒数と対処法が出る"""
    with pytest.raises(OllamaTimeoutError) as excinfo:
        with ollama_errors("glm-ocr", 300):
            raise httpx.ReadTimeout("timed out")

    message = str(excinfo.value)
    assert "300 秒" in message
    assert "generate_timeout_seconds" in message


def test_other_response_errors_pass_through():
    """"not found" 以外の ResponseError はそのまま投げ直す（握りつぶさない）"""
    with pytest.raises(ollama.ResponseError):
        with ollama_errors("glm-ocr", 300):
            raise ollama.ResponseError("internal server error", 500)


def test_httpx_timeout_is_not_connection_error():
    """この設計の前提: httpxのtimeoutは組み込み例外のどれでもない

    ollama-python が将来 TimeoutException も変換するようになったら
    このテストが落ちるので、ollama_errors の設計を見直せる。
    """
    error = httpx.ReadTimeout("x")

    assert not isinstance(error, ConnectionError)
    assert not isinstance(error, TimeoutError)


# ---------- OllamaOCRClient.ocr() の経路 ----------


class _FakeChatClient:
    """chat() の引数を記録し、指定した例外を投げるだけのフェイク

    ollama.Client の代わりに chat_client() から返させる。
    raises: 毎回投げる例外
    raises_first: 最初の n 回だけ投げる例外のリスト（再試行の検証用）
    content / done_reason: 成功時の応答
    """

    def __init__(
        self,
        raises: BaseException | None = None,
        *,
        raises_first: list[BaseException] | None = None,
        content: str = "  読み取ったテキスト  ",
        done_reason: str = "stop",
    ):
        self.raises = raises
        self.raises_first = list(raises_first or [])
        self.content = content
        self.done_reason = done_reason
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        # 再試行で options を書き換えられても記録が変わらないよう写しを残す
        self.calls.append({**kwargs, "options": dict(kwargs.get("options") or {})})
        if self.raises is not None:
            raise self.raises
        if len(self.calls) <= len(self.raises_first):
            raise self.raises_first[len(self.calls) - 1]

        class _Message:
            pass

        class _Response:
            pass

        response = _Response()
        response.message = _Message()
        response.message.content = self.content
        response.done_reason = self.done_reason
        return response


class _FakeListClient:
    """list() の呼び出し回数を数えるフェイク"""

    def __init__(self, model_names=("glm-ocr:latest",)):
        self.model_names = model_names
        self.calls = 0

    def list(self):
        self.calls += 1

        class _Entry:
            def __init__(self, name):
                self.model = name

        class _Models:
            pass

        models = _Models()
        models.models = [_Entry(n) for n in self.model_names]
        return models


def _dummy_png(tmp_path):
    """OCRに渡せる最小の実在画像を作る（_validate_image を通すため）"""
    img = np.full((40, 60, 3), 255, dtype=np.uint8)
    path = tmp_path / "page.png"
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))
    return path


@pytest.fixture
def fake_ollama(monkeypatch):
    """chat_client / list_client を差し替えて実Ollamaなしで ocr() を回す"""
    chat = _FakeChatClient()
    listing = _FakeListClient()
    monkeypatch.setattr(ollama_client, "chat_client", lambda: chat)
    monkeypatch.setattr(ollama_client, "list_client", lambda: listing)
    return chat, listing


def test_ocr_passes_options_to_chat(tmp_path, fake_ollama):
    """G4の本体: temperature=0 が実際に chat へ渡っている"""
    chat, _ = fake_ollama

    result = OllamaOCRClient().ocr(_dummy_png(tmp_path))

    assert chat.calls[0]["options"]["temperature"] == 0.0
    assert chat.calls[0]["options"]["seed"] == 0
    # 使ったパラメータは結果にも残る（meta.json に記録するため）
    assert result.options["temperature"] == 0.0
    assert result.text == "読み取ったテキスト"


def test_ocr_raises_timeout_error(tmp_path, monkeypatch, fake_ollama):
    """無応答は OllamaTimeoutError になる（無限ハングしない）"""
    _, listing = fake_ollama
    monkeypatch.setattr(
        ollama_client,
        "chat_client",
        lambda: _FakeChatClient(raises=httpx.ReadTimeout("timed out")),
    )

    with pytest.raises(OllamaTimeoutError):
        OllamaOCRClient().ocr(_dummy_png(tmp_path))


def test_model_check_runs_once_per_client(tmp_path, fake_ollama):
    """モデル存在確認はページごとに繰り返さない"""
    _, listing = fake_ollama
    client = OllamaOCRClient()
    image = _dummy_png(tmp_path)

    client.ocr(image)
    client.ocr(image)

    assert listing.calls == 1



def test_missing_model_is_not_memoized(tmp_path, monkeypatch):
    """モデルが無い場合は記憶せず毎回raiseする（失敗を握りつぶさない）"""
    listing = _FakeListClient(model_names=("qwen3.5:9b",))
    monkeypatch.setattr(ollama_client, "list_client", lambda: listing)
    client = OllamaOCRClient()
    image = _dummy_png(tmp_path)

    for _ in range(2):
        with pytest.raises(OllamaModelNotFoundError):
            client.ocr(image)

    assert listing.calls == 2


# ---------- G12: 切り落とし・上限到達・反復の再試行 ----------


def _repeat_error():
    """Ollama の反復検知が返す ResponseError（実物の文言）"""
    return ollama.ResponseError(
        '{"error":"prediction aborted, token repeat limit reached"}', 500
    )


def _use_chat(monkeypatch, chat):
    monkeypatch.setattr(ollama_client, "chat_client", lambda: chat)
    return chat


def test_ocr_trims_repetition(tmp_path, monkeypatch, fake_ollama):
    """ocr() の結果は切り落とし後の本文で、切った字数が残る"""
    kept = "\n".join([_HEADING, *_BODY])
    raw = "\n".join([kept, *_BODY, *_BODY])
    _use_chat(monkeypatch, _FakeChatClient(content=raw))

    result = OllamaOCRClient().ocr(_dummy_png(tmp_path))

    assert result.text == kept
    assert result.trimmed_chars == len(raw) - len(kept)


def test_ocr_without_repetition_has_no_trim(tmp_path, fake_ollama):
    """反復が無ければ trimmed_chars は 0、上限到達も無し"""
    result = OllamaOCRClient().ocr(_dummy_png(tmp_path))

    assert result.trimmed_chars == 0
    assert result.hit_limit is False
    assert result.attempts == 1


@pytest.mark.parametrize("done_reason, expected", [("length", True), ("stop", False)])
def test_hit_limit_follows_done_reason(
    tmp_path, monkeypatch, fake_ollama, done_reason, expected
):
    """done_reason == "length"（num_predict で打ち切り）のときだけ hit_limit"""
    _use_chat(monkeypatch, _FakeChatClient(done_reason=done_reason))

    result = OllamaOCRClient().ocr(_dummy_png(tmp_path))

    assert result.hit_limit is expected


def test_num_predict_reaches_chat(tmp_path, fake_ollama):
    """上限は実際に chat の options に渡り、再試行回数は渡らない"""
    chat, _ = fake_ollama

    OllamaOCRClient().ocr(_dummy_png(tmp_path))

    assert chat.calls[0]["options"]["num_predict"] == 1024
    assert "retry_on_repeat" not in chat.calls[0]["options"]


@pytest.fixture
def retry_once(monkeypatch):
    """再試行を 1 回に設定する（既定は 0 回）"""
    monkeypatch.setattr(
        ollama_client,
        "CONFIG",
        _FakeConfig({"ocr": {"temperature": 0.0, "seed": 0}, "ocr.retry_on_repeat": 1}),
    )


def test_repeat_error_is_retried_with_another_seed(
    tmp_path, monkeypatch, fake_ollama, retry_once
):
    """仕様「再試行で成功する」: 1 回目が反復検知でも、シードを変えた 2 回目で成功する"""
    chat = _use_chat(monkeypatch, _FakeChatClient(raises_first=[_repeat_error()]))

    result = OllamaOCRClient().ocr(_dummy_png(tmp_path))

    assert result.text == "読み取ったテキスト"
    assert result.attempts == 2
    assert len(chat.calls) == 2
    assert chat.calls[0]["options"]["seed"] == 0
    assert chat.calls[1]["options"]["seed"] != chat.calls[0]["options"]["seed"]
    # 記録に残る options は成功した試行のもの
    assert result.options["seed"] == chat.calls[1]["options"]["seed"]


def test_repeat_error_after_all_retries(tmp_path, monkeypatch, fake_ollama, retry_once):
    """仕様「再試行しても失敗する」: 再試行を使い切ったら OllamaRepeatError"""
    chat = _use_chat(monkeypatch, _FakeChatClient(raises=_repeat_error()))

    with pytest.raises(OllamaRepeatError) as excinfo:
        OllamaOCRClient().ocr(_dummy_png(tmp_path))

    assert len(chat.calls) == 2  # 初回 + 再試行 1 回
    assert "再試行" in str(excinfo.value)


def test_no_retry_by_default(tmp_path, monkeypatch, fake_ollama):
    """仕様「既定では再試行しない」: 反復検知は 1 回で OllamaRepeatError になる"""
    chat = _use_chat(monkeypatch, _FakeChatClient(raises=_repeat_error()))

    with pytest.raises(OllamaRepeatError):
        OllamaOCRClient().ocr(_dummy_png(tmp_path))

    assert len(chat.calls) == 1


def test_other_errors_are_not_retried(tmp_path, monkeypatch, fake_ollama, retry_once):
    """反復以外の失敗（タイムアウト等）は再試行しない（待ち時間を倍にしない）"""
    chat = _use_chat(
        monkeypatch, _FakeChatClient(raises=httpx.ReadTimeout("timed out"))
    )

    with pytest.raises(OllamaTimeoutError):
        OllamaOCRClient().ocr(_dummy_png(tmp_path))

    assert len(chat.calls) == 1


# ---------- Ollama のバージョン ----------


class _FakeVersionClient:
    """_request_raw("GET", "/api/version") だけを持つフェイク"""

    def __init__(self, version="0.40.2"):
        self.version = version
        self.requests: list[tuple] = []

    def _request_raw(self, method, url):
        self.requests.append((method, url))

        class _Response:
            def __init__(self, version):
                self._version = version

            def json(self):
                return {"version": self._version}

        return _Response(self.version)


def test_ollama_version(monkeypatch):
    """/api/version の version をそのまま返す"""
    fake = _FakeVersionClient()
    monkeypatch.setattr(ollama_client, "list_client", lambda: fake)

    assert ollama_version() == "0.40.2"
    assert fake.requests == [("GET", "/api/version")]
