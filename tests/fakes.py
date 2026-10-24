"""テスト用の手書きフェイク（複数のテストファイルで共有する）

Ollama にも NDLOCR-Lite にも頼らずに OCR パイプラインを動かすための最小限の偽物。
プロジェクトの決めごとにより unittest.mock は使わず、必要な振る舞いだけを持つ
クラスを手で書く。本番の OllamaOCRClient / TextModernizer とはダックタイピングで
差し替える（ocr() / modernize_detailed() と model 属性があればよい）。

tests/ には __init__.py が無く、pytest の既定動作で tests/ が import パスに入るため
`from fakes import FakeClient` で読み込める。
"""

from pathlib import Path

from utils.ndlocr_client import REQUIRED_FILES
from utils.ollama_client import OCRResult
from utils.text_modernizer import ModernizeResult


class FakeClient:
    """指定したページ番号で例外を投げるOCRクライアント

    fail_at: {1始まりのページ番号: 投げる例外} を渡す。
    texts: ページごとに返す本文。省略時は「ページNの本文」を返す。
    extras: {1始まりのページ番号: OCRResult に足す属性}（例: {"trimmed_chars": 120}）。
            反復の切り落とし・上限到達・再試行が起きたページを再現するために使う。
    calls に実際に呼ばれた回数が残るので、打ち切りの検証にも使える。
    """

    model = "fake-ocr"

    def __init__(
        self,
        fail_at: dict[int, BaseException] | None = None,
        texts: list[str] | None = None,
        extras: dict[int, dict] | None = None,
    ):
        self.fail_at = fail_at or {}
        self.texts = texts
        self.extras = extras or {}
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
            **self.extras.get(self.calls, {}),
        )


class NameEchoClient:
    """画像のファイル名をそのまま本文にして返すOCRクライアント

    FakeClient の本文は「呼ばれた順」の番号なので、結合後の本文がどの画像の順かを
    見分けられない。こちらは画像名が本文に入るため、ページ順の検証に使う。
    """

    model = "fake-ocr"

    def __init__(self):
        self.calls = 0

    def ocr(self, image_path):
        self.calls += 1
        return OCRResult(
            text=f"本文:{Path(image_path).name}",
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


# ---------- NDLOCR-Lite ----------
# 行データは実機の json_lines の形だけを写した架空のもの（資料の本文は入れない）。
# 縦書きのページを右から左へ読む。列の幅 30、本文の列の長さは 1000（y=100〜1100）。


def ndlocr_line(text, x0, y0, x1, y1, *, vertical, confidence=0.95):
    """実機の json_lines と同じ形の 1 行（boundingBox の 4 点の並びも実機どおり）"""
    return {
        "boundingBox": [[x0, y0], [x0, y1], [x1, y0], [x1, y1]],
        "id": 0,
        "isVertical": "true" if vertical else "false",
        "text": text,
        "isTextline": "true",
        "confidence": confidence,
        "class_index": 1,
    }


def ndlocr_column(text, x, length=1000, top=100, confidence=0.95):
    """縦書きの 1 列（x は列の左端）"""
    return ndlocr_line(text, x, top, x + 30, top + length, vertical=True, confidence=confidence)


def install_fake_ndlocr(root: Path, skip=()) -> Path:
    """NDLOCR-Lite の導入に要るファイルを空で置く（skip に挙げたものは置かない）"""
    for name in REQUIRED_FILES:
        if name in skip:
            continue
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"")
    return root


class FakeNdlocrBackend:
    """NDLOCR-Lite の読み込みと認識の偽物（NdlocrLiteClient の backend= に渡す）

    lines: recognize が返す行のリスト
    import_error / load_error: 読み込みで投げる例外
    recognize_errors: {1始まりの呼び出し回数: 投げる例外}
    imports / loads / recognized に呼ばれた回数と画像名が残る。
    """

    def __init__(self, lines=None, import_error=None, load_error=None, recognize_errors=None):
        self.lines = lines if lines is not None else [ndlocr_column("本文ノ列", 900)]
        self.import_error = import_error
        self.load_error = load_error
        self.recognize_errors = recognize_errors or {}
        self.imports = 0
        self.loads = 0
        self.recognized: list[str] = []

    def import_module(self, root):
        self.imports += 1
        if self.import_error is not None:
            raise self.import_error

    def load_models(self, root):
        self.loads += 1
        if self.load_error is not None:
            raise self.load_error

    def recognize(self, image, name):
        self.recognized.append(name)
        error = self.recognize_errors.get(len(self.recognized))
        if error is not None:
            raise error
        assert image.ndim == 3 and image.shape[2] == 3  # RGB の配列で渡る
        return self.lines

