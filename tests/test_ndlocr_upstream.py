"""NDLOCR-Lite 本体との結合テスト（design.md の D8）

vendor/ndlocr-lite を取得済みの環境でだけ、テスト内で描いた縦書きの画像を本物の NDLOCR-Lite で読み、
行のリスト（json_lines）の形が整形（shape_ndlocr_lines）の前提どおりかを確かめる。
版を上げて上流の内部関数（_run_ocr_on_image_array など）が変わったときに、ここで気づける。

資料は使わない。取得していない環境（git submodule update をしていない）や日本語フォントが無い環境では skip する。
モデルの読み込みに数秒かかる。
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from utils.ndlocr_client import NdlocrLiteClient, UpstreamBackend, missing_files, ndlocr_path

# 縦書きの画像を描くための日本語フォントの候補（macOS・Linux）
_FONT_CANDIDATES = (
    "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)

# 架空の文（資料の本文ではない）。右の列から読む
_COLUMNS = ("東京市役所ニ於テ本日會議ヲ開ク", "出席者ハ左ノ通リナリ")


def _skip_reason(root: Path, fonts: tuple[str, ...] = _FONT_CANDIDATES) -> str | None:
    """結合テストを skip する理由（走らせられるなら None）"""
    if missing_files(root):
        return f"NDLOCR-Lite を取得していない（{root}）。git submodule update --init --depth 1 で取得できる"
    if not any(Path(font).is_file() for font in fonts):
        return "縦書きの画像を描く日本語フォントが無い"
    return None


def _draw_vertical_page() -> Image.Image:
    """縦書きの 2 列を描いた白い画像"""
    font_path = next(font for font in _FONT_CANDIDATES if Path(font).is_file())
    font = ImageFont.truetype(font_path, 36)
    image = Image.new("RGB", (400, 700), "white")
    draw = ImageDraw.Draw(image)
    for column, text in enumerate(_COLUMNS):
        x = 300 - column * 70
        for row, char in enumerate(text):
            draw.text((x, 40 + row * 40), char, font=font, fill="black")
    return image


def test_skip_when_not_fetched(tmp_path):
    """取得していない環境では skip する（理由に取得方法が入る）"""
    reason = _skip_reason(tmp_path)

    assert reason is not None
    assert "git submodule update --init --depth 1" in reason


def test_skip_without_japanese_font(tmp_path):
    """取得済みでも日本語フォントが無ければ skip する"""
    root = ndlocr_path()
    if missing_files(root):
        pytest.skip("NDLOCR-Lite を取得していない")

    assert _skip_reason(root, fonts=(str(tmp_path / "no-font.ttc"),)) == "縦書きの画像を描く日本語フォントが無い"


@pytest.mark.skipif(_skip_reason(ndlocr_path()) is not None, reason=str(_skip_reason(ndlocr_path())))
def test_upstream_lines_match_shaping_assumptions(tmp_path):
    """本物の NDLOCR-Lite の行のリストが、キー・型とも整形の前提どおりで、本文が空でない"""
    image = _draw_vertical_page()
    path = tmp_path / "synthetic.png"
    image.save(path)
    backend = UpstreamBackend()
    client = NdlocrLiteClient(backend=backend)

    result = client.ocr(path)  # 事前確認とモデルの読み込みを通す
    lines = backend.recognize(np.array(image), path.name)

    assert lines
    for line in lines:
        assert isinstance(line["text"], str)
        assert isinstance(line["confidence"], float)
        assert line["isVertical"] in ("true", "false")
        assert len(line["boundingBox"]) == 4
        assert all(len(point) == 2 for point in line["boundingBox"])
    assert any(line["isVertical"] == "true" for line in lines)
    assert result.text.strip()
    assert result.model == "ndlocr-lite"
