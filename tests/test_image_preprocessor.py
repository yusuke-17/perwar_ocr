"""画像前処理（A1）のテスト

cv2 で合成画像を作り、前処理の各ステップ・二値化オプション・傾き検出・
日本語パス対応を検証する（Ollama/LLM不要）。
"""

import cv2
import numpy as np

from utils.image_preprocessor import (
    PreprocessOptions,
    _detect_skew_angle,
    preprocess_image,
)


# ---------- ヘルパー ----------


def _make_doc_image(width: int = 400, height: int = 300) -> "np.ndarray":
    """白背景に黒い文字風の矩形を並べた合成文書画像（BGR）を作る"""
    img = np.full((height, width, 3), 255, dtype=np.uint8)
    # 黒い「文字行」を数本描く
    for y in range(40, height - 40, 50):
        cv2.rectangle(img, (30, y), (width - 30, y + 20), (0, 0, 0), -1)
    return img


def _write(path, img) -> None:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    buf.tofile(str(path))


def _preset(binarize: str = "none") -> PreprocessOptions:
    return PreprocessOptions(
        deskew=True, denoise=True, contrast=True, binarize=binarize
    )


# ---------- preprocess_image ----------


def test_preprocess_creates_output(tmp_path):
    """前処理後画像が生成され、読み込み可能"""
    src = tmp_path / "src.png"
    out = tmp_path / "out.png"
    _write(src, _make_doc_image())

    result = preprocess_image(src, out, _preset())

    assert out.exists()
    data = np.fromfile(str(out), dtype=np.uint8)
    assert cv2.imdecode(data, cv2.IMREAD_GRAYSCALE) is not None
    assert result.output_path == out
    assert result.elapsed_seconds >= 0.0


def test_steps_conservative_preset(tmp_path):
    """保守プリセットでは grayscale/clahe を含み、二値化は含まない"""
    src = tmp_path / "src.png"
    out = tmp_path / "out.png"
    _write(src, _make_doc_image())

    result = preprocess_image(src, out, _preset(binarize="none"))

    assert "grayscale" in result.steps
    assert "clahe" in result.steps
    assert not any(s.startswith("binarize") for s in result.steps)


def test_binarize_option(tmp_path):
    """binarize=otsu で出力が2値（0/255のみ）になる"""
    src = tmp_path / "src.png"
    out = tmp_path / "out.png"
    _write(src, _make_doc_image())

    result = preprocess_image(src, out, _preset(binarize="otsu"))

    assert "binarize:otsu" in result.steps
    data = np.fromfile(str(out), dtype=np.uint8)
    gray = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    assert set(np.unique(gray)).issubset({0, 255})


def test_detect_skew_angle(tmp_path):
    """既知角度で回した画像の傾きを概ね検出する"""
    img = _make_doc_image()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    matrix = cv2.getRotationMatrix2D((w // 2, h // 2), 5.0, 1.0)
    rotated = cv2.warpAffine(
        gray, matrix, (w, h), borderValue=255
    )

    angle = _detect_skew_angle(rotated)
    # 5度回した画像なので、無視できない傾きを検出するはず（符号はバージョン差を許容）
    assert 2.0 <= abs(angle) <= 8.0


def test_unicode_path(tmp_path):
    """日本語ファイル名でも読み書きできる"""
    src = tmp_path / "テスト画像.png"
    out = tmp_path / "出力_前処理.png"
    _write(src, _make_doc_image())

    result = preprocess_image(src, out, _preset())

    assert out.exists()
    assert result.steps  # 何らかの処理が適用されている
