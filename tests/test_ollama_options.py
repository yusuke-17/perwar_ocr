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
    OllamaTimeoutError,
    chat_client,
    generate_timeout,
    list_client,
    list_timeout,
    ocr_options,
    ollama_errors,
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
    """

    def __init__(self, raises: BaseException | None = None):
        self.raises = raises
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises

        class _Message:
            content = "  読み取ったテキスト  "

        class _Response:
            message = _Message()

        return _Response()


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
