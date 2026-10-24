"""
NDLOCR-Lite クライアント

国立国会図書館の NDLOCR-Lite（CPU で動く ONNX 版の OCR）を、プロジェクトと同じ実行環境で呼び出す。
NDLOCR-Lite はパッケージとしては入れず、submodule で置いたソース（vendor/ndlocr-lite）を
sys.path の末尾に足して読み込む（上流の配布設定の不具合で、インストールすると起動しないため）。
設計は openspec/changes/ndlocr-lite-engine/design.md の D2〜D4。

このモジュールの役割:
- NdlocrLiteClient: OllamaOCRClient と同じ形（ocr() と model 属性）で OCRResult を返す。
  モデルは 1 クライアントにつき最初の 1 回だけ読み込み、ページ間で使い回す
- NDLOCR-Lite が返す行のリストを、以降の処理（正規化・口語化・保存・検索）に使える本文へ整える（純粋関数）
- 認識の信頼度が低い行を数える（純粋関数）
- 導入の確認（ファイルの有無と import）と版の取得。prewar check からも使う

使い方:
    client = NdlocrLiteClient()
    result = client.ocr("input/image.png")
    print(result.text)
"""

import argparse
import importlib
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from utils.config import CONFIG, PROJECT_ROOT
from utils.ollama_client import ImageFileError, OCRResult, validate_image

# ---------- 定数 ----------

# エンジン名（[models] ocr / --model に書く値。記録の model にも残る）
NDLOCR_ENGINE = "ndlocr-lite"

# 版が取れないときに記録へ残す値
UNKNOWN_VERSION = "不明"

# v1.3.1 の CLI の既定値（src/ocr.py の main()）を写したもの。版を上げたらここも見直す
_DET_MODEL = "deim-s-1024x1024.onnx"
_REC_MODEL_30 = "parseq-ndl-24x256-30-tiny-189epoch-tegaki3-r8data-202604.onnx"
_REC_MODEL_50 = "parseq-ndl-24x384-50-tiny-300epoch-tegaki3-r8data-202604.onnx"
_REC_MODEL_100 = "parseq-ndl-24x768-100-tiny-153epoch-tegaki3-r8data-202604.onnx"
_DET_CLASSES = "ndl.yaml"
_REC_CLASSES = "NDLmoji.yaml"
_DET_THRESHOLDS = {"det_score_threshold": 0.2, "det_conf_threshold": 0.25, "det_iou_threshold": 0.2}

# 導入済みと言えるために要るファイル（NDLOCR-Lite のソース直下からの相対パス）
REQUIRED_FILES = (
    "src/ocr.py",
    f"src/config/{_DET_CLASSES}",
    f"src/config/{_REC_CLASSES}",
    f"src/model/{_DET_MODEL}",
    f"src/model/{_REC_MODEL_30}",
    f"src/model/{_REC_MODEL_50}",
    f"src/model/{_REC_MODEL_100}",
)

# 未導入のときに案内する手順（どちらが原因でも両方出す）
INSTALL_HINT = (
    "→ プロジェクト直下で次を実行してください:\n"
    "   git submodule update --init --depth 1   # NDLOCR-Lite のソースとモデルを取得\n"
    "   uv sync                                 # 実行に要るパッケージを導入\n"
    "→ GLM-OCR で読む場合は --model glm-ocr を付けてください"
)

# この割合に満たない列（見出し・段落の終わり）の後で改行する。
# 根拠は design.md の D3（手元 10 枚の全行を計測。本文の列は最長の 0.96〜1.00、段落の終わりは 0.83〜0.88）。
# 利用者が調整する値ではないので設定にはしない。
_SHORT_LINE_RATIO = 0.9

# 非 ASCII 文字（日本語）に隣り合う半角空白。NDLOCR-Lite は読点の後などに入れてくる。
# 英字どうしの間の空白は残す。全角空白は資料の字下げの可能性があるので触らない。
_SPACES_NEAR_NON_ASCII = re.compile(r"(?<=[^\x00-\x7f]) +| +(?=[^\x00-\x7f])")


# ---------- 設定 ----------
# import 時に定数へ焼き込まず、呼び出しのたびに読む（設定の差し替えを効かせるため）


def ndlocr_path() -> Path:
    """NDLOCR-Lite のソースの場所（[ndlocr] path）。相対パスはプロジェクト直下から解決する"""
    path = Path(CONFIG.get("ndlocr.path", "vendor/ndlocr-lite")).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def low_confidence_threshold() -> float:
    """低信頼度の警告を出す閾値（[ndlocr] low_confidence）"""
    return float(CONFIG.get("ndlocr.low_confidence", 0.7))


# ---------- 出力の整形 ----------


@dataclass(frozen=True)
class _Line:
    """整形に使う 1 行（縦書きなら 1 列）の文字と位置"""

    text: str
    vertical: bool
    x0: float
    x1: float
    y0: float
    y1: float

    @property
    def length(self) -> float:
        """列の長さ（縦書きは高さ、横書きは幅）"""
        return (self.y1 - self.y0) if self.vertical else (self.x1 - self.x0)


def _to_line(raw: dict) -> _Line | None:
    """NDLOCR-Lite の 1 行を _Line にする。空白を除いて字が残らない行は None"""
    text = _SPACES_NEAR_NON_ASCII.sub("", str(raw.get("text") or "")).strip(" ")
    if not text:
        return None
    xs = [float(point[0]) for point in raw["boundingBox"]]
    ys = [float(point[1]) for point in raw["boundingBox"]]
    # isVertical は文字列 "true" / "false"（JSON 出力と同じ形）
    vertical = str(raw.get("isVertical")).lower() == "true"
    return _Line(text, vertical, min(xs), max(xs), min(ys), max(ys))


def _continues(cur: _Line, nxt: _Line) -> bool:
    """nxt が cur と同じ列の続き（縦書きなら真下、横書きなら真右）か

    括弧書きの位置などで、1 本の列が上下 2 つの行に分かれて出力されることがある。
    """
    if cur.vertical != nxt.vertical:
        return False
    if cur.vertical:
        return cur.x0 < nxt.x1 and nxt.x0 < cur.x1 and nxt.y0 >= cur.y1
    return cur.y0 < nxt.y1 and nxt.y0 < cur.y1 and nxt.x0 >= cur.x1


def shape_ndlocr_lines(lines: list[dict]) -> str:
    """NDLOCR-Lite の行のリストを本文に整える（純粋関数）

    1. 行は読み順（リストの並び）のまま使い、空の行は捨てる
    2. 日本語の文字に隣り合う半角空白を取り除く
    3. 列は改行を挟まずにつなぐ。ただし次の場合は列の後で改行する
       - 同じ向きの最長の列の 9 割に満たない列（見出し・段落の終わり）。
         次の行が同じ列の続き（真下）なら改行しない
       - 縦書きと横書きが切り替わるところ（本文の途中に来るページ番号などを列にくっつけない）
    字を加えたり変えたりはしない。最後の行の後には改行を入れない。

    Args:
        lines: `_run_ocr_on_image_array` が返す `json_lines`
               （各行に text・isVertical・boundingBox）

    Returns:
        整えた本文。行が無ければ空文字列
    """
    items = [line for line in map(_to_line, lines) if line is not None]
    longest: dict[bool, float] = {}
    for item in items:
        longest[item.vertical] = max(longest.get(item.vertical, 0.0), item.length)

    parts: list[str] = []
    for cur, nxt in zip(items, items[1:] + [None]):
        parts.append(cur.text)
        if nxt is None or _continues(cur, nxt):
            continue
        short = cur.length < longest[cur.vertical] * _SHORT_LINE_RATIO
        if short or cur.vertical != nxt.vertical:
            parts.append("\n")
    return "".join(parts)


def count_low_confidence(lines: list[dict], threshold: float) -> int:
    """認識の信頼度が閾値未満の行の数（純粋関数）。閾値ちょうどは数えない"""
    return sum(1 for line in lines if float(line.get("confidence", 1.0)) < threshold)


# ---------- 例外クラス ----------


class NdlocrNotInstalledError(Exception):
    """NDLOCR-Lite のソースやモデルが無い、または読み込めない場合の例外（エンジン未導入）"""

    pass


class NdlocrError(Exception):
    """NDLOCR-Lite の認識中にエラーが出た場合の例外"""

    pass


# ---------- 導入の確認と版 ----------


def missing_files(root: Path) -> list[str]:
    """導入に要るファイルのうち、root に無いもの（REQUIRED_FILES の並び）"""
    return [name for name in REQUIRED_FILES if not (root / name).is_file()]


def read_ndlocr_version(root: Path) -> str:
    """NDLOCR-Lite の版（submodule のタグ。例: "1.3.1"）。取れなければ「不明」

    上流の pyproject.toml と --version は配布用ビルドでしか正しい版にならないため、タグから取る。
    root 自体が git の作業ツリーでない（手で置いた）ときは、外側のプロジェクトのタグを拾わないよう「不明」にする。
    """
    if not (root / ".git").exists():
        return UNKNOWN_VERSION
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--exact-match"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN_VERSION  # git が無い・固まった
    version = completed.stdout.strip()
    return version if completed.returncode == 0 and version else UNKNOWN_VERSION


class Backend(Protocol):
    """NDLOCR-Lite の読み込みと認識の口（テストでは手書きの偽物に差し替える）"""

    def import_module(self, root: Path) -> None:
        """NDLOCR-Lite のコードを読み込む（モデルは読まない）。失敗は例外のまま出す"""

    def load_models(self, root: Path) -> None:
        """検出・認識のモデルを読み込む（数秒かかる）。失敗は例外のまま出す"""

    def recognize(self, image, name: str) -> list[dict]:
        """RGB の画像配列 1 枚を読み、行のリスト（json_lines）を返す"""


class UpstreamBackend:
    """本物の NDLOCR-Lite（vendor/ndlocr-lite のソース）を呼ぶバックエンド

    公式の安定 API ではない内部関数（get_detector・get_recognizer・_run_ocr_on_image_array）に頼る。
    submodule でコミットごと固定しているので勝手には変わらない。版を上げたら結合テストで確かめる。
    """

    def __init__(self):
        self._ocr = None
        self._models = None

    def import_module(self, root: Path) -> None:
        src = root / "src"
        # 末尾に足す: src には ocr・config・model など一般的な名前があり、先頭だと他の import を横取りする
        if str(src) not in sys.path:
            sys.path.append(str(src))
        module = importlib.import_module("ocr")
        origin = Path(module.__file__ or "").resolve()
        if origin != (src / "ocr.py").resolve():
            raise ImportError(f"別の ocr モジュールが読み込まれました: {origin}")
        self._ocr = module

    def load_models(self, root: Path) -> None:
        model_dir = root / "src" / "model"
        config_dir = root / "src" / "config"
        args = argparse.Namespace(
            det_weights=str(model_dir / _DET_MODEL),
            det_classes=str(config_dir / _DET_CLASSES),
            rec_weights30=str(model_dir / _REC_MODEL_30),
            rec_weights50=str(model_dir / _REC_MODEL_50),
            rec_weights=str(model_dir / _REC_MODEL_100),
            rec_classes=str(config_dir / _REC_CLASSES),
            device="cpu",
            enable_tcy=False,
            **_DET_THRESHOLDS,
        )
        ocr = self._ocr
        self._models = (
            ocr.get_detector(args),
            ocr.get_recognizer(args, weights_path=args.rec_weights30),
            ocr.get_recognizer(args, weights_path=args.rec_weights50),
            ocr.get_recognizer(args),
        )

    def recognize(self, image, name: str) -> list[dict]:
        detector, rec30, rec50, rec100 = self._models
        # 可視化しないので出力先には何も書かれないが、引数として要るので一時ディレクトリを渡す
        with tempfile.TemporaryDirectory() as outdir:
            result = self._ocr._run_ocr_on_image_array(
                detector, rec30, rec50, rec100, name, image, outdir, save_viz=False
            )
        return result["json_lines"]


def verify_installation(root: Path | None = None, backend: Backend | None = None) -> Path:
    """NDLOCR-Lite が使える状態か確かめる（ファイルの有無と import。モデルは読まない）

    Returns:
        確かめたソースの場所
    Raises:
        NdlocrNotInstalledError: ソース・モデルが無い、または import に失敗した（依存不足など）
    """
    root = root or ndlocr_path()
    backend = backend or UpstreamBackend()
    missing = missing_files(root)
    if len(missing) == len(REQUIRED_FILES):
        raise NdlocrNotInstalledError(
            f"NDLOCR-Lite のソースが見つかりません: {root}\n{INSTALL_HINT}"
        )
    if missing:
        raise NdlocrNotInstalledError(
            f"NDLOCR-Lite のファイルが足りません: {', '.join(missing)}\n{INSTALL_HINT}"
        )
    try:
        backend.import_module(root)
    except Exception as e:
        raise NdlocrNotInstalledError(
            f"NDLOCR-Lite を読み込めません（{type(e).__name__}: {e}）\n{INSTALL_HINT}"
        ) from e
    return root


# ---------- メインクラス ----------


def _read_rgb(path: Path):
    """画像を RGB の配列で読む（NDLOCR-Lite の CLI と同じく Pillow で開いて RGB にする）"""
    import numpy as np
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as image:
            return np.array(image.convert("RGB"))
    except (OSError, UnidentifiedImageError) as e:
        raise ImageFileError(f"画像を開けません: {path.name}（{e}）") from e


class NdlocrLiteClient:
    """
    NDLOCR-Lite を使った OCR クライアント（OllamaOCRClient と同じ ocr() / model の形）

    使い方:
        client = NdlocrLiteClient()
        result = client.ocr("input/image.png")

    Args:
        root: NDLOCR-Lite のソースの場所（省略時は [ndlocr] path）
        backend: 読み込みと認識の口（省略時は本物の NDLOCR-Lite。テストで差し替える）
        version_reader: 版を取る関数（省略時は git のタグ。テストで差し替える）
    """

    model = NDLOCR_ENGINE

    def __init__(
        self,
        root: Path | None = None,
        *,
        backend: Backend | None = None,
        version_reader: Callable[[Path], str] = read_ndlocr_version,
    ):
        self._root = root
        self._backend = backend or UpstreamBackend()
        self._version_reader = version_reader
        # 事前確認とモデルの読み込みは成功したときだけ覚える（失敗したら次のページでも確かめる）
        self._verified_root: Path | None = None
        self._models_loaded = False
        self._version: str | None = None

    @property
    def engine_version(self) -> str:
        """NDLOCR-Lite の版（1 クライアントにつき 1 回だけ取る）"""
        if self._version is None:
            self._version = self._version_reader(self._root or ndlocr_path())
        return self._version

    def ocr(self, image_path: str | Path) -> OCRResult:
        """
        画像ファイルからテキストを読み取る

        Raises:
            ImageFileError: 画像が無い・非対応の形式・開けない
            NdlocrNotInstalledError: NDLOCR-Lite が導入されていない・読み込めない
            NdlocrError: 認識中に NDLOCR-Lite がエラーを出した
        """
        path = validate_image(Path(image_path))
        self._prepare()
        image = _read_rgb(path)

        start_time = time.time()
        try:
            lines = self._backend.recognize(image, path.name)
        except Exception as e:
            raise NdlocrError(
                f"NDLOCR-Lite の認識中にエラーが発生しました（{type(e).__name__}: {e}）"
            ) from e
        elapsed = time.time() - start_time  # 初回のモデル読み込みは含めない

        return OCRResult(
            text=shape_ndlocr_lines(lines),
            model=self.model,
            image_path=str(path),
            elapsed_seconds=elapsed,
            prompt="",
            options={},
            low_confidence_lines=count_low_confidence(lines, low_confidence_threshold()),
            engine_version=self.engine_version,
        )

    def _prepare(self) -> None:
        """事前確認（ファイルと import）とモデルの読み込みを、成功するまで 1 回ずつ行う"""
        if self._verified_root is None:
            self._verified_root = verify_installation(self._root, self._backend)
        if self._models_loaded:
            return
        start_time = time.time()
        try:
            self._backend.load_models(self._verified_root)
        except Exception as e:
            raise NdlocrNotInstalledError(
                f"NDLOCR-Lite のモデルを読み込めません（{type(e).__name__}: {e}）\n{INSTALL_HINT}"
            ) from e
        self._models_loaded = True
        print(f"  NDLOCR-Lite のモデルを読み込みました（{time.time() - start_time:.1f}秒）")

