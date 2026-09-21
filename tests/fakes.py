"""テスト用の手書きフェイク（複数のテストファイルで共有する）

Ollama に接続せずに OCR パイプラインを動かすための最小限の偽物。
プロジェクトの決めごとにより unittest.mock は使わず、必要な振る舞いだけを持つ
クラスを手で書く。本番の OllamaOCRClient / TextModernizer とはダックタイピングで
差し替える（ocr() / modernize_detailed() と model 属性があればよい）。

tests/ には __init__.py が無く、pytest の既定動作で tests/ が import パスに入るため
`from fakes import FakeClient` で読み込める。
"""

from utils.ollama_client import OCRResult
from utils.text_modernizer import ModernizeResult


class FakeClient:
    """指定したページ番号で例外を投げるOCRクライアント

    fail_at: {1始まりのページ番号: 投げる例外} を渡す。
    texts: ページごとに返す本文。省略時は「ページNの本文」を返す。
    calls に実際に呼ばれた回数が残るので、打ち切りの検証にも使える。
    """

    model = "fake-ocr"

    def __init__(
        self,
        fail_at: dict[int, BaseException] | None = None,
        texts: list[str] | None = None,
    ):
        self.fail_at = fail_at or {}
        self.texts = texts
        self.calls = 0

    def ocr(self, image_path):
        self.calls += 1
        error = self.fail_at.get(self.calls)
        if error is not None:
            raise error
        if self.texts is not None:
            text = self.texts[self.calls - 1]
        else:
            text = f"ページ{self.calls}の本文"
        return OCRResult(
            text=text,
            model=self.model,
            image_path=str(image_path),
            elapsed_seconds=0.1,
            prompt="テスト用",
        )


class StubModernizer:
    """modernize_detailed だけを持つ最小のスタブ（固定の結果か例外を返す）"""

    model = "qwen3.5:9b"

    def __init__(self, result=None, error: BaseException | None = None):
        self.result = result
        self.error = error

    def modernize_detailed(self, text: str):
        if self.error is not None:
            raise self.error
        return self.result


# 口語化を「通った」ことを保存物から判定するための目印
MODERN_MARK = "口語:"


class EchoModernizer:
    """入力の先頭に目印を付けて返す口語化フェイク

    保存された modern.txt が「口語化を通ったもの」か
    「正規化テキストのまま（口語化の省略・失敗）」かを見分けるために使う。
    """

    model = "fake-llm"

    def __init__(self):
        self.calls = 0

    def modernize_detailed(self, text: str) -> ModernizeResult:
        self.calls += 1
        return ModernizeResult(text=f"{MODERN_MARK}{text}", chunk_total=1)
