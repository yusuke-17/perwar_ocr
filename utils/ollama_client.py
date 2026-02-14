"""
Ollama API ラッパー

Vision LLM（GLM-OCR等）を使って画像からテキストを抽出する。
Ollamaサーバーとの通信、エラーハンドリング、結果の整形を担当。
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------- 定数 ----------

DEFAULT_MODEL = "glm-ocr"

DEFAULT_PROMPT = "画像内のテキストをすべて正確に読み取ってください。"

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}


# ---------- データクラス ----------


@dataclass
class OCRResult:
    """OCR処理の結果を格納するデータクラス"""

    text: str  # 認識されたテキスト
    model: str  # 使用したモデル名
    image_path: str  # 処理した画像のパス
    elapsed_seconds: float  # 処理にかかった秒数
    prompt: str  # 使用したプロンプト
    raw_response: dict = field(default_factory=dict)  # Ollamaの生レスポンス情報


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

        start_time = time.time()
        text, raw_info = self._call_ollama(path)
        elapsed = time.time() - start_time

        return OCRResult(
            text=text,
            model=self.model,
            image_path=str(path),
            elapsed_seconds=elapsed,
            prompt=self.prompt,
            raw_response=raw_info,
        )

    def is_available(self) -> bool:
        """Ollamaサーバーに接続でき、指定モデルが利用可能かチェック"""
        try:
            self._check_model_available()
            return True
        except (OllamaConnectionError, OllamaModelNotFoundError):
            return False

    def list_models(self) -> list[str]:
        """インストール済みモデルの一覧を返す"""
        import ollama

        try:
            models = ollama.list()
            return [m.model for m in models.models]
        except ConnectionError:
            raise OllamaConnectionError(
                "Ollamaサーバーに接続できません。\n"
                "→ Ollama.app を起動してください（メニューバーにアイコンが出ます）"
            )

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
        """指定モデルがOllamaにインストール済みかチェック"""
        model_names = self.list_models()
        # "glm-ocr" が "glm-ocr:latest" にマッチするようにする
        found = any(self.model in name for name in model_names)
        if not found:
            raise OllamaModelNotFoundError(
                f"モデル '{self.model}' が見つかりません。\n"
                f"→ ollama pull {self.model} を実行してください\n"
                f"インストール済み: {', '.join(model_names) or '(なし)'}"
            )

    def _call_ollama(self, image_path: Path) -> tuple[str, dict]:
        """Ollama APIを呼び出してOCR結果を取得する"""
        import ollama

        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": self.prompt,
                        "images": [str(image_path)],
                    }
                ],
            )
        except ConnectionError:
            raise OllamaConnectionError(
                "Ollamaサーバーに接続できません。\n"
                "→ Ollama.app を起動してください（メニューバーにアイコンが出ます）"
            )
        except ollama.ResponseError as e:
            if "not found" in str(e).lower():
                raise OllamaModelNotFoundError(
                    f"モデル '{self.model}' が見つかりません。\n"
                    f"→ ollama pull {self.model} を実行してください"
                )
            raise

        text = response.message.content.strip()

        raw_info = {
            "total_duration_ns": getattr(response, "total_duration", None),
            "prompt_eval_count": getattr(response, "prompt_eval_count", None),
            "eval_count": getattr(response, "eval_count", None),
            "eval_duration_ns": getattr(response, "eval_duration", None),
        }

        return text, raw_info
