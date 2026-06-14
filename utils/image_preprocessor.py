"""
画像前処理モジュール（OCR入力前の整形）

戦前文書（黄ばみ・かすれ・斜めスキャン・シミ）はそのままだと Vision OCR が
読み違えやすい。OCRへ渡す直前に以下を適用して読み取りを安定させる:

  1. グレースケール化  （処理の基底。常時）
  2. 傾き補正(deskew)  （微小な傾きを水平に戻す）
  3. ノイズ除去        （紙のシミ・点ノイズを軽く除去）
  4. コントラスト強調  （CLAHE。かすれた文字を浮かせる）
  5. 二値化            （任意。既定OFF。Vision OCRでは細い画数が潰れうるため）

設定は config.toml の [preprocess] セクション（既定は utils/config.py の _DEFAULTS）。

注意: cv2.imread/imwrite は非ASCIIパス（日本語ファイル名）で失敗しうるため、
np.fromfile + cv2.imdecode / cv2.imencode + tofile で読み書きする。
"""

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from utils.config import CONFIG

# ---------- データクラス ----------


@dataclass
class PreprocessOptions:
    """前処理の各ステップのON/OFF設定"""

    deskew: bool
    denoise: bool
    contrast: bool
    binarize: str  # "none" | "otsu" | "adaptive"


@dataclass
class PreprocessResult:
    """前処理の結果"""

    output_path: Path  # 前処理後画像のパス
    steps: list[str]  # 実際に適用した処理名のリスト
    elapsed_seconds: float


# ---------- 例外クラス ----------


class PreprocessError(Exception):
    """画像の読み込み・前処理・書き出しに失敗した場合の例外"""

    pass


# ---------- 設定読み込み ----------


def options_from_config(binarize_override: str | None = None) -> PreprocessOptions:
    """config から PreprocessOptions を組み立てる。

    Args:
        binarize_override: 指定時は config の binarize 設定を上書きする
            （CLI の --binarize 用）。

    Returns:
        PreprocessOptions
    """
    return PreprocessOptions(
        deskew=CONFIG.get("preprocess.deskew", True),
        denoise=CONFIG.get("preprocess.denoise", True),
        contrast=CONFIG.get("preprocess.contrast", True),
        binarize=binarize_override or CONFIG.get("preprocess.binarize", "none"),
    )


# ---------- 内部ヘルパー ----------


def _imread_unicode(path: Path) -> "np.ndarray":
    """日本語パス対応で画像を読み込む（BGR）。失敗時 PreprocessError。"""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError as e:
        raise PreprocessError(f"画像を読み込めません: {path}\n→ {e}") from e
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise PreprocessError(f"画像をデコードできません（破損/非対応形式）: {path}")
    return image


def _imwrite_unicode(path: Path, image: "np.ndarray") -> None:
    """日本語パス対応で画像を書き出す。失敗時 PreprocessError。"""
    ext = path.suffix or ".png"
    ok, buf = cv2.imencode(ext, image)
    if not ok:
        raise PreprocessError(f"画像をエンコードできません: {path}")
    buf.tofile(str(path))


def _detect_skew_angle(gray: "np.ndarray") -> float:
    """文字画素の minAreaRect から傾き角（度）を推定する純粋関数。

    正の角度は時計回りの傾き。文字がほぼ無い画像では 0.0 を返す。
    """
    # 文字を白(前景)に反転し、Otsuで2値化して前景座標を集める
    inverted = cv2.bitwise_not(gray)
    threshed = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(threshed > 0))
    if coords.shape[0] < 10:
        return 0.0

    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    # minAreaRect の角度はOpenCVバージョンで [-90,0) / [0,90) と揺れるため正規化する
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    return float(angle)


def _rotate(image: "np.ndarray", angle: float) -> "np.ndarray":
    """画像を angle 度だけ回転して傾きを補正する（端は近傍画素で補完）。"""
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


# ---------- 公開関数 ----------

# 補正対象とする傾き角の範囲（度）。微小すぎる傾きは無視し、
# 大きすぎる角度は右横書き等の誤検出とみなして補正しない。
_SKEW_MIN_DEG = 0.5
_SKEW_MAX_DEG = 15.0


def preprocess_image(
    input_path: Path,
    output_path: Path,
    options: PreprocessOptions | None = None,
) -> PreprocessResult:
    """input_path を読み込み、設定に従って前処理し output_path に保存する。

    Args:
        input_path: 元画像のパス
        output_path: 前処理後画像の保存先
        options: 前処理設定（省略時は config から読む）

    Returns:
        PreprocessResult（保存先・適用した処理名・処理秒数）

    Raises:
        PreprocessError: 読み込み・書き出しに失敗した場合
    """
    options = options or options_from_config()
    start = time.perf_counter()
    steps: list[str] = []

    image = _imread_unicode(input_path)

    # ① グレースケール化（常時）
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    steps.append("grayscale")

    # ② 傾き補正（微小〜中程度の傾きのみ）
    if options.deskew:
        angle = _detect_skew_angle(gray)
        if _SKEW_MIN_DEG <= abs(angle) <= _SKEW_MAX_DEG:
            gray = _rotate(gray, angle)
            steps.append(f"deskew:{angle:.1f}")

    # ③ ノイズ除去（軽め）
    if options.denoise:
        gray = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
        steps.append("denoise")

    # ④ コントラスト強調（CLAHE）
    if options.contrast:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        steps.append("clahe")

    # ⑤ 二値化（任意・既定OFF）
    if options.binarize == "otsu":
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        steps.append("binarize:otsu")
    elif options.binarize == "adaptive":
        gray = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
        )
        steps.append("binarize:adaptive")

    _imwrite_unicode(output_path, gray)

    return PreprocessResult(
        output_path=output_path,
        steps=steps,
        elapsed_seconds=time.perf_counter() - start,
    )
