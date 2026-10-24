"""
Ollama API ラッパー

Vision LLM（GLM-OCR等）を使って画像からテキストを抽出する。
Ollamaサーバーとの通信、エラーハンドリング、結果の整形を担当。
"""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from utils.config import CONFIG

# ---------- 定数 ----------

# Ollama で OCR するときの既定のモデル。どのエンジンで読むか（NDLOCR-Lite か Ollama のモデルか）は
# 設定の [models] ocr と --model が決める（scripts/ocr_vision_llm.py の _ocr_engine）
DEFAULT_MODEL = "glm-ocr"

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
    trimmed_chars: int = 0  # 反復として切り落とした字数（0 なら切り落とし無し）
    hit_limit: bool = False  # 生成トークン数の上限（num_predict）に達して終わったか
    attempts: int = 1  # 反復による失敗の再試行を含めた試行回数
    low_confidence_lines: int = 0  # 認識の信頼度が閾値未満の行の数（NDLOCR-Lite のみ）
    engine_version: str = ""  # OCR エンジンの版（NDLOCR-Lite のみ。取れなければ「不明」）


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


class OllamaRepeatError(Exception):
    """Ollamaの反復検知で生成が打ち切られた場合の例外

    Ollama 0.34.1 以降は、モデルが同じトークンを繰り返し続けると
    HTTP 500 `token repeat limit reached` を返して出力を捨てる。
    """

    pass


# ---------- 画像の検証 ----------


def validate_image(image_path: Path) -> Path:
    """画像ファイルの存在と拡張子を検証し、絶対パスを返す

    OCR エンジンによらず同じ規則で検証する（OllamaOCRClient と NdlocrLiteClient で共有）。
    """
    path = image_path.resolve()

    if not path.exists():
        raise ImageFileError(f"ファイルが見つかりません: {image_path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ImageFileError(f"非対応の画像形式です: {ext}\n" f"対応形式: {supported}")

    return path


# ---------- 反復の切り落とし ----------


# 反復判定の閾値（根拠は openspec/changes/archive/2026-10-18-g12-ocr-repetition-loop/design.md の D1）
_SIMILAR_LINE_MIN_CHARS = 30  # これより短い行は完全一致だけで判定する（1字違いの表の行を守る）
_SIMILAR_LINE_RATIO = 0.95  # 実際に反復した行の類似度は 0.99 以上だった
_INLINE_FRAGMENT_CHARS = 20  # 行の中で再び現れたら反復と見なす文字列の長さ
_INLINE_MIN_DISTINCT = 5  # これより字の種類が少ない文字列（罫線・同じ字の連続）は除く


def _is_similar_line(prev: str, line: str) -> bool:
    """2つの行が「OCR の読み違いを含む同じ行」と言えるほど似ているか"""
    if min(len(prev), len(line)) < _SIMILAR_LINE_MIN_CHARS:
        return False
    matcher = SequenceMatcher(None, prev, line, autojunk=False)
    # 安い上限見積もりで先に弾いてから、本当の類似度を計算する
    return (
        matcher.real_quick_ratio() >= _SIMILAR_LINE_RATIO
        and matcher.quick_ratio() >= _SIMILAR_LINE_RATIO
        and matcher.ratio() >= _SIMILAR_LINE_RATIO
    )


def _inline_repeat_at(line: str) -> int | None:
    """1行の中で同じ文字列が重ならずに再び現れた位置（行頭からの字数）。無ければ None"""
    size = _INLINE_FRAGMENT_CHARS
    first_seen: dict[str, int] = {}
    for pos in range(len(line) - size + 1):
        fragment = line[pos : pos + size]
        start = first_seen.setdefault(fragment, pos)
        if pos - start >= size and len(set(fragment)) >= _INLINE_MIN_DISTINCT:
            return pos
    return None


def trim_repetition(text: str) -> tuple[str, int]:
    """OCR 出力の反復が始まった位置から後ろを切り落とす（純粋関数）

    glm-ocr は縦書き・旧字体の資料で、実内容を読み終えたあと同じ内容を延々と繰り返す。
    実内容は必ず出力の冒頭にまとまるため、反復の始まりで切れば本文は欠けない。
    行を順に見て、次のどれかに最初に当たった位置で切る（空行は判定に使わない）。

    1. 既出の行と同じ行（前後の空白は除いて比べる）
    2. 既出の行とよく似た長い行（繰り返すたびに似た字へ読み違えるため、完全一致しないことが多い）
    3. 1行の中で再び現れた同じ文字列（改行を出さずに繰り返す場合）

    Returns:
        (切り落とし後のテキスト, 切り落とした字数)。反復が無ければ (text, 0) をそのまま返す
    """
    seen: list[str] = []
    offset = 0
    cut: int | None = None
    for line in text.splitlines(keepends=True):
        key = line.strip()
        if key:
            if key in seen or any(_is_similar_line(prev, key) for prev in seen):
                cut = offset
                break
            inline = _inline_repeat_at(key)
            if inline is not None:
                cut = offset + line.index(key) + inline
                break
            seen.append(key)
        offset += len(line)

    if cut is None:
        return text, 0
    kept = text[:cut].rstrip()
    return kept, len(text) - len(kept)


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


# [ocr] セクションのうち、Ollama の options に渡さないキー
_OCR_NON_OPTION_KEYS = ("retry_on_repeat",)


def ocr_options() -> dict:
    """OCRの生成パラメータ（config.toml の [ocr] セクション）

    そのまま ollama の options= に渡る。毎回新しいdictを返すのは、
    渡した先で書き換えられてもグローバル設定が汚れないようにするため。
    retry_on_repeat（生成パラメータではない）は取り除き、
    num_predict が 0 以下なら渡さない（＝無制限。timeout の 0 と同じ流儀）。
    """
    options = dict(CONFIG.get("ocr") or {})
    for key in _OCR_NON_OPTION_KEYS:
        options.pop(key, None)
    if "num_predict" in options and int(options["num_predict"]) <= 0:
        del options["num_predict"]
    return options


def ocr_retry_count() -> int:
    """反復による失敗のとき何回まで再試行するか（[ocr] retry_on_repeat）。0 以下は再試行しない"""
    return max(0, int(CONFIG.get("ocr.retry_on_repeat", 0)))


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


def ollama_version() -> str:
    """Ollama サーバーのバージョン（例: "0.40.2"）を返す

    ollama-python には専用メソッドが無いため、Client の内部メソッドで /api/version を叩く。
    Ollama.app は自動更新されるので、反復検知など挙動が変わったときの切り分けに使う。
    失敗時は例外がそのまま出る（呼び出し側で「不明」として扱う）。
    """
    with ollama_errors("", list_timeout()):
        response = list_client()._request_raw("GET", "/api/version")
    return str(response.json()["version"])


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
        # Ollama の反復検知: "prediction aborted, token repeat limit reached"（HTTP 500）。
        # 文言が将来変わったら、ここの判定文字列だけ直せばよい
        if e.status_code == 500 and "repeat" in str(e).lower():
            raise OllamaRepeatError(
                "OCRエンジンが同じ内容を繰り返したため、Ollama が出力を打ち切りました（反復検知）。\n"
                f"→ 詳細: {e.error}"
            ) from e
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
        path = validate_image(Path(image_path))
        self._check_model_available()

        retries = ocr_retry_count()
        start_time = time.time()
        for attempt in range(1, retries + 2):
            options = ocr_options()
            if attempt > 1:
                # temperature=0 でもシードが変われば反復の形が変わり、反復検知を抜けうる
                options["seed"] = int(options.get("seed", 0)) + attempt - 1
            try:
                raw_text, done_reason = self._call_ollama(path, options)
                break
            except OllamaRepeatError as e:
                if attempt > retries:
                    if retries:
                        raise OllamaRepeatError(
                            f"{e}\n→ シードを変えて {retries} 回再試行しましたが同じでした"
                        ) from e
                    raise
        elapsed = time.time() - start_time  # 再試行した分の時間も含める

        text, trimmed = trim_repetition(raw_text)
        return OCRResult(
            text=text,
            model=self.model,
            image_path=str(path),
            elapsed_seconds=elapsed,
            prompt=self.prompt,
            options=options,
            trimmed_chars=trimmed,
            hit_limit=done_reason == "length",
            attempts=attempt,
        )

    def list_models(self) -> list[str]:
        """インストール済みモデルの一覧を返す"""
        with ollama_errors(self.model, list_timeout()):
            models = list_client().list()
        return [m.model for m in models.models]

    # ---------- プライベートメソッド ----------

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

    def _call_ollama(self, image_path: Path, options: dict) -> tuple[str, str | None]:
        """Ollama APIを呼び出してOCR結果を取得する

        Args:
            image_path: 読み取る画像
            options: 生成パラメータ（temperature=0 等。config.toml の [ocr]）

        Returns:
            (認識テキスト, done_reason)。done_reason は "stop"（自然に終了）か
            "length"（num_predict の上限で打ち切り）
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

        return response.message.content.strip(), response.done_reason
