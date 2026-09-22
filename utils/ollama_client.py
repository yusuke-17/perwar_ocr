"""
Ollama API ラッパー

Vision LLM（GLM-OCR等）を使って画像からテキストを抽出する。
Ollamaサーバーとの通信、エラーハンドリング、結果の整形を担当。
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from utils.config import CONFIG

# ---------- 定数 ----------

DEFAULT_MODEL = CONFIG.get("models.ocr")

DEFAULT_PROMPT = "画像内のテキストをすべて正確に読み取ってください。"

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}

# config.toml が壊れている等で設定が読めない場合の保険
_FALLBACK_GENERATE_TIMEOUT = 300.0
_FALLBACK_LIST_TIMEOUT = 15.0


# ---------- データクラス ----------


@dataclass
class OCRResult:
    """OCR処理の結果を格納するデータクラス"""

    text: str  # 認識されたテキスト
    model: str  # 使用したモデル名
    image_path: str  # 処理した画像のパス
    elapsed_seconds: float  # 処理にかかった秒数
    prompt: str  # 使用したプロンプト
    options: dict = field(default_factory=dict)  # 実際に渡した生成パラメータ


# ---------- 例外クラス ----------


class OllamaConnectionError(Exception):
    """Ollamaサーバーに接続できない場合の例外"""

    pass


class OllamaModelNotFoundError(Exception):
    """指定したモデルがインストールされていない場合の例外"""

    pass


class ImageFileError(Exception):
    """画像ファイルに問題がある場合の例外"""

    pass


class OllamaTimeoutError(Exception):
    """Ollamaが制限時間内に応答しなかった場合の例外"""

    pass


# ---------- Ollama 呼び出しの共通設定 ----------
# OCRも口語体変換も環境確認も、Ollamaを叩くときは必ずこの層を通す。
# モジュールレベルの ollama.chat() / ollama.list() は内部の既定クライアントを使い、
# その timeout が None（無制限）なので、Ollamaが固まると永久に戻らないため。


def _timeout(key: str, fallback: float) -> float | None:
    """configからtimeout秒数を読む。0以下なら None＝無制限（従来の挙動に戻す抜け道）

    import時に定数へ焼き込まず呼び出しのたびに読む（設定差し替えを効かせるため）。
    """
    value = float(CONFIG.get(key, fallback))
    return value if value > 0 else None


def generate_timeout() -> float | None:
    """chat（生成）1回あたりの上限秒数"""
    return _timeout("ollama.generate_timeout_seconds", _FALLBACK_GENERATE_TIMEOUT)


def list_timeout() -> float | None:
    """list（モデル一覧）など軽いAPIの上限秒数"""
    return _timeout("ollama.list_timeout_seconds", _FALLBACK_LIST_TIMEOUT)


def ocr_options() -> dict:
    """OCRの生成パラメータ（config.toml の [ocr] セクション）

    そのまま ollama の options= に渡る。毎回新しいdictを返すのは、
    渡した先で書き換えられてもグローバル設定が汚れないようにするため。
    """
    return dict(CONFIG.get("ocr") or {})


def chat_client():
    """timeout付きの ollama.Client（生成用）を返す

    毎回作るのは意図的。Client生成は1ms未満で、数秒〜数分かかる生成に比べれば
    無視できる。プロセス寿命のキャッシュを持たない方が、設定変更もテストの
    差し替えも素直になる。import は遅延のまま（起動を遅くしない既存方針）。
    """
    import ollama

    return ollama.Client(timeout=generate_timeout())


def list_client():
    """timeout付きの ollama.Client（モデル一覧など軽いAPI用）を返す"""
    import ollama

    return ollama.Client(timeout=list_timeout())


@contextmanager
def ollama_errors(model: str, timeout: float | None):
    """Ollama呼び出しの例外をプロジェクト共通の例外へ翻訳する

    ollama-python は httpx の例外のうち ConnectError と HTTPStatusError しか
    変換せず、TimeoutException（ReadTimeout / ConnectTimeout 等）はそのまま
    漏れてくる。ここで受け止めないと呼び出し側の except ConnectionError を素通りする。

    Args:
        model: エラーメッセージに出すモデル名
        timeout: 適用した上限秒数（None は無制限）
    """
    import httpx
    import ollama

    try:
        yield
    except httpx.TimeoutException as e:
        limit = f"{timeout:.0f} 秒" if timeout else "制限時間"
        raise OllamaTimeoutError(
            f"Ollamaが {limit} 以内に応答しませんでした。\n"
            f"→ Ollama.app が固まっていないか確認してください（再起動で直ることがあります）\n"
            f"→ 大きな画像や重いモデルで時間がかかるのが正常なら、config.toml の\n"
            f"   [ollama] generate_timeout_seconds を延ばしてください（現在 {limit}）"
        ) from e
    except ConnectionError as e:
        raise OllamaConnectionError(
            "Ollamaサーバーに接続できません。\n"
            "→ Ollama.app を起動してください（メニューバーにアイコンが出ます）"
        ) from e
    except ollama.ResponseError as e:
        if "not found" in str(e).lower():
            raise OllamaModelNotFoundError(
                f"モデル '{model}' が見つかりません。\n"
                f"→ ollama pull {model} を実行してください"
            ) from e
        raise


# ---------- メインクラス ----------


class OllamaOCRClient:
    """
    Ollama Vision LLM を使ったOCRクライアント

    使い方:
        client = OllamaOCRClient()
        result = client.ocr("input/image.png")
        print(result.text)

        # モデルを変更する場合
        client = OllamaOCRClient(model="qwen3-vl")
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        prompt: str = DEFAULT_PROMPT,
    ):
        self.model = model
        self.prompt = prompt
        # モデルの存在確認を1インスタンス1回で済ませるためのメモ（成功時のみ立てる）
        self._model_checked = False

    def ocr(self, image_path: str | Path) -> OCRResult:
        """
        画像ファイルからテキストを読み取る

        Args:
            image_path: 画像ファイルのパス

        Returns:
            OCRResult: 認識結果
        """
        path = self._validate_image(Path(image_path))
        self._check_model_available()

        options = ocr_options()

        start_time = time.time()
        text = self._call_ollama(path, options)
        elapsed = time.time() - start_time

        return OCRResult(
            text=text,
            model=self.model,
            image_path=str(path),
            elapsed_seconds=elapsed,
            prompt=self.prompt,
            options=options,
        )

    def list_models(self) -> list[str]:
        """インストール済みモデルの一覧を返す"""
        with ollama_errors(self.model, list_timeout()):
            models = list_client().list()
        return [m.model for m in models.models]

    # ---------- プライベートメソッド ----------

    def _validate_image(self, image_path: Path) -> Path:
        """画像ファイルの存在と拡張子を検証する"""
        path = image_path.resolve()

        if not path.exists():
            raise ImageFileError(f"ファイルが見つかりません: {image_path}")

        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ImageFileError(
                f"非対応の画像形式です: {ext}\n" f"対応形式: {supported}"
            )

        return path

    def _check_model_available(self) -> None:
        """指定モデルがOllamaにインストール済みかチェック

        成功したら記憶し、同じクライアントでは2回目以降スキップする
        （バッチでページ数ぶん ollama.list() を投げないため）。
        失敗は記憶しないので、モデル未インストールなら毎回ちゃんと raise する。
        """
        if self._model_checked:
            return

        model_names = self.list_models()
        # "glm-ocr" が "glm-ocr:latest" にマッチするようにする
        found = any(self.model in name for name in model_names)
        if not found:
            raise OllamaModelNotFoundError(
                f"モデル '{self.model}' が見つかりません。\n"
                f"→ ollama pull {self.model} を実行してください\n"
                f"インストール済み: {', '.join(model_names) or '(なし)'}"
            )

        self._model_checked = True

    def _call_ollama(self, image_path: Path, options: dict) -> str:
        """Ollama APIを呼び出してOCR結果を取得する

        Args:
            image_path: 読み取る画像
            options: 生成パラメータ（temperature=0 等。config.toml の [ocr]）
        """
        with ollama_errors(self.model, generate_timeout()):
            response = chat_client().chat(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": self.prompt,
                        "images": [str(image_path)],
                    }
                ],
                options=options,
            )

        return response.message.content.strip()
