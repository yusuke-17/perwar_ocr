"""NDLOCR-Lite クライアントのテスト

NDLOCR-Lite も Ollama も無しで通る。行データは実機の JSON（`json_lines`）の形だけを写した架空のもので
（tests/fakes.py の ndlocr_line / ndlocr_column）、資料の本文は入れない（G12 で決めた方針）。
"""

import shutil
import subprocess

import pytest
from PIL import Image

from utils import ndlocr_client
from utils.config import _DEFAULTS, PROJECT_ROOT
from utils.ndlocr_client import (
    NdlocrError,
    NdlocrLiteClient,
    NdlocrNotInstalledError,
    count_low_confidence,
    read_ndlocr_version,
    shape_ndlocr_lines,
)
from utils.ollama_client import ImageFileError, ocr_options

from fakes import FakeNdlocrBackend as FakeBackend
from fakes import install_fake_ndlocr as _install
from fakes import ndlocr_column as _col
from fakes import ndlocr_line as _line

# ---------- 出力の整形 ----------


def test_columns_are_joined_without_newline():
    """文の途中で列が変わっても、改行を挟まずにつながる（列をまたぐ語を検索で引ける）"""
    lines = [_col("一ノ列ハ途中デ次", 900), _col("ノ列ニ続ク", 860)]

    assert shape_ndlocr_lines(lines) == "一ノ列ハ途中デ次ノ列ニ続ク"


def test_heading_becomes_its_own_line():
    """短い見出しの列の後で改行し、見出しが本文の最初の行になる"""
    lines = [_col("第一章　見出", 940, length=300), _col("本文ノ一列目", 900), _col("本文ノ二列目", 860)]

    text = shape_ndlocr_lines(lines)

    assert text == "第一章　見出\n本文ノ一列目本文ノ二列目"
    assert text.splitlines()[0] == "第一章　見出"


def test_spaces_after_punctuation_are_removed():
    """日本語に隣り合う半角空白は消え、読点と次の字が直接つながる"""
    lines = [_col("本令ハ、 公布ノ日ヨリ  之ヲ施行ス", 900)]

    assert shape_ndlocr_lines(lines) == "本令ハ、公布ノ日ヨリ之ヲ施行ス"


def test_spaces_between_ascii_words_are_kept():
    """英字どうしの間の空白は残す（全角空白も字下げの可能性があるので触らない）"""
    lines = [_col("Tokyo Station 驛　前", 900)]

    assert shape_ndlocr_lines(lines) == "Tokyo Station驛　前"


def test_paragraph_end_breaks_line():
    """列の 8 割あたりで終わる段落の最後の列の後で改行し、次の段落は新しい行から始まる"""
    lines = [
        _col("前ノ段落ノ列", 900),
        _col("前ノ段落ノ終リ。", 860, length=820),
        _col("次ノ段落ノ列", 820),
    ]

    assert shape_ndlocr_lines(lines) == "前ノ段落ノ列前ノ段落ノ終リ。\n次ノ段落ノ列"


def test_split_column_is_joined():
    """1 本の列が上下 2 つの行に分かれて出力されても、真下に続くなら改行しない"""
    lines = [
        _col("列ノ上部（括弧", 900, length=600, top=100),
        _col("書キ）列ノ下部", 902, length=380, top=720),
        _col("次ノ列", 860),
    ]

    assert shape_ndlocr_lines(lines) == "列ノ上部（括弧書キ）列ノ下部\n次ノ列"


def test_split_column_needs_overlap_and_below():
    """隣の列（x が重ならない）や上に戻る行は、短ければ改行する"""
    lines = [
        _col("短イ列", 900, length=400, top=100),
        _col("隣ノ列", 860, length=400, top=600),  # 下にあるが x が重ならない
        _col("本文", 820),
    ]

    assert shape_ndlocr_lines(lines) == "短イ列\n隣ノ列\n本文"


def test_horizontal_page_number_does_not_disturb_vertical_columns():
    """横書きのページ番号が本文の途中に混ざっても、縦書きの最長は乱れず、列にくっつかない

    実機では、ページ番号（横書きの 2 字）が縦書きの本文の列の間に出力されるページがある。
    横書きの行は 1 本だけだと横書きの中で最長になるため、向きの切り替わりで改行する。
    """
    lines = [
        _col("一列目", 900),
        _col("短イ列", 860, length=500),
        _line("12", 500, 1150, 560, 1180, vertical=False, confidence=0.6),
        _col("三列目", 820),
        _col("四列目", 780),
    ]

    assert shape_ndlocr_lines(lines) == "一列目短イ列\n12\n三列目四列目"


def test_empty_lines_are_dropped():
    """空の行（空白だけの行も）は捨て、改行の判定にも使わない"""
    lines = [_col("一列目", 900), _col("", 880, length=100), _col("  ", 870, length=100), _col("二列目", 860)]

    assert shape_ndlocr_lines(lines) == "一列目二列目"


def test_no_lines_gives_empty_text():
    """行が無いページは空文字列"""
    assert shape_ndlocr_lines([]) == ""


def test_last_line_has_no_trailing_newline():
    """最後の行が短くても、後ろに改行は付けない"""
    lines = [_col("本文", 900), _col("署名", 860, length=200)]

    assert shape_ndlocr_lines(lines) == "本文署名"


def test_horizontal_lines_are_joined_like_columns():
    """横書きのページでは、行の幅で同じ規則が働く"""
    lines = [
        _line("見出シ", 100, 100, 400, 130, vertical=False),
        _line("横書キノ本文一行目", 100, 150, 1100, 180, vertical=False),
        _line("二行目", 100, 190, 1100, 220, vertical=False),
    ]

    assert shape_ndlocr_lines(lines) == "見出シ\n横書キノ本文一行目二行目"


# ---------- 低信頼度の行 ----------


def test_count_low_confidence_lines():
    """閾値未満の行だけを数える"""
    lines = [_col("一", 900, confidence=0.95), _col("二", 860, confidence=0.6), _col("三", 820, confidence=0.69)]

    assert count_low_confidence(lines, 0.7) == 2


def test_count_low_confidence_threshold_is_exclusive():
    """閾値ちょうどの行は数えない"""
    assert count_low_confidence([_col("一", 900, confidence=0.7)], 0.7) == 0


def test_count_low_confidence_without_lines():
    """行が無ければ 0"""
    assert count_low_confidence([], 0.7) == 0


# ---------- 設定 ----------


class _FakeConfig:
    """CONFIG.get だけを差し替える最小のフェイク（utils.config.Config と同じドット記法）"""

    def __init__(self, values: dict):
        self._values = values

    def get(self, dotted_key, default=None):
        return self._values.get(dotted_key, default)


def test_ndlocr_defaults():
    """既定はソースが vendor/ndlocr-lite、閾値 0.7"""
    assert _DEFAULTS["ndlocr"] == {"path": "vendor/ndlocr-lite", "low_confidence": 0.7}


def test_ndlocr_settings_do_not_leak_into_ocr_options():
    """[ndlocr] の値は Ollama の options（[ocr]）に混ざらない"""
    options = ocr_options()

    assert "path" not in options
    assert "low_confidence" not in options


def test_relative_path_is_resolved_from_project_root(monkeypatch):
    """相対パスはカレントディレクトリではなくプロジェクト直下から解決する"""
    monkeypatch.setattr(ndlocr_client, "CONFIG", _FakeConfig({"ndlocr.path": "somewhere/ndlocr"}))
    monkeypatch.chdir("/")

    assert ndlocr_client.ndlocr_path() == PROJECT_ROOT / "somewhere/ndlocr"


def test_absolute_path_is_used_as_is(monkeypatch, tmp_path):
    """絶対パスはそのまま使う（別の場所に置いた利用者のため）"""
    monkeypatch.setattr(ndlocr_client, "CONFIG", _FakeConfig({"ndlocr.path": str(tmp_path)}))

    assert ndlocr_client.ndlocr_path() == tmp_path


def test_low_confidence_threshold_from_config(monkeypatch):
    """閾値は設定で変えられる"""
    monkeypatch.setattr(ndlocr_client, "CONFIG", _FakeConfig({"ndlocr.low_confidence": 0.5}))

    assert ndlocr_client.low_confidence_threshold() == 0.5


# ---------- NdlocrLiteClient（偽のバックエンドで動かす） ----------

def _image(tmp_path, name="page.png"):
    path = tmp_path / name
    Image.new("RGB", (40, 60), "white").save(path)
    return path


def _client(root, backend, version="1.3.1"):
    return NdlocrLiteClient(root, backend=backend, version_reader=lambda _root: version)


def test_ocr_returns_shaped_text_and_metadata(tmp_path):
    """本文は整形済みで、NDLOCR-Lite には切り落としも上限到達も無い"""
    backend = FakeBackend(lines=[_col("本令ハ、 公布", 900), _col("ノ日ヨリ施行ス", 860)])
    client = _client(_install(tmp_path / "ndlocr"), backend)

    result = client.ocr(_image(tmp_path))

    assert result.text == "本令ハ、公布ノ日ヨリ施行ス"
    assert result.model == "ndlocr-lite"
    assert result.trimmed_chars == 0
    assert result.hit_limit is False
    assert result.prompt == ""
    assert result.options == {}
    assert result.engine_version == "1.3.1"


def test_low_confidence_lines_are_counted(tmp_path):
    """閾値（既定 0.7）未満の行の数が OCRResult に入る"""
    backend = FakeBackend(lines=[_col("本文", 900), _col("12", 860, length=50, confidence=0.6)])
    client = _client(_install(tmp_path / "ndlocr"), backend)

    assert client.ocr(_image(tmp_path)).low_confidence_lines == 1


def test_models_are_loaded_only_once(tmp_path):
    """2 枚読んでも、事前確認・モデルの読み込み・版の取得は 1 回だけ"""
    backend = FakeBackend()
    versions = []
    client = NdlocrLiteClient(
        _install(tmp_path / "ndlocr"),
        backend=backend,
        version_reader=lambda root: versions.append(root) or "1.3.1",
    )

    client.ocr(_image(tmp_path, "1.png"))
    client.ocr(_image(tmp_path, "2.png"))

    assert backend.imports == 1
    assert backend.loads == 1
    assert backend.recognized == ["1.png", "2.png"]
    assert len(versions) == 1


def test_model_load_time_is_shown_once(tmp_path, capsys):
    """モデルの読み込みにかかった時間は、最初のページでだけ画面に出る"""
    client = _client(_install(tmp_path / "ndlocr"), FakeBackend())

    client.ocr(_image(tmp_path, "1.png"))
    client.ocr(_image(tmp_path, "2.png"))

    assert capsys.readouterr().out.count("モデルを読み込みました") == 1


def _assert_install_hint(message: str):
    assert "git submodule update --init --depth 1" in message
    assert "uv sync" in message


def test_missing_source_is_not_installed(tmp_path):
    """ソースが無い（submodule 未取得）なら未導入。import は試さない"""
    backend = FakeBackend()
    client = _client(tmp_path / "empty", backend)

    with pytest.raises(NdlocrNotInstalledError) as excinfo:
        client.ocr(_image(tmp_path))

    assert "ソースが見つかりません" in str(excinfo.value)
    _assert_install_hint(str(excinfo.value))
    assert backend.imports == 0


def test_missing_model_is_not_installed(tmp_path):
    """モデルが 1 本でも足りなければ未導入で、足りないファイルを名指しする"""
    missing = "src/model/deim-s-1024x1024.onnx"
    client = _client(_install(tmp_path / "ndlocr", skip={missing}), FakeBackend())

    with pytest.raises(NdlocrNotInstalledError) as excinfo:
        client.ocr(_image(tmp_path))

    assert missing in str(excinfo.value)
    _assert_install_hint(str(excinfo.value))


def test_import_failure_is_not_installed(tmp_path):
    """import に失敗（依存が足りない）したら未導入"""
    backend = FakeBackend(import_error=ModuleNotFoundError("No module named 'onnxruntime'"))
    client = _client(_install(tmp_path / "ndlocr"), backend)

    with pytest.raises(NdlocrNotInstalledError) as excinfo:
        client.ocr(_image(tmp_path))

    assert "onnxruntime" in str(excinfo.value)
    _assert_install_hint(str(excinfo.value))


def test_model_load_failure_is_not_installed(tmp_path):
    """モデルを読み込めない（壊れている等）ときも未導入。次のページでも読み込みを試す"""
    backend = FakeBackend(load_error=RuntimeError("bad onnx"))
    client = _client(_install(tmp_path / "ndlocr"), backend)

    for _ in range(2):
        with pytest.raises(NdlocrNotInstalledError):
            client.ocr(_image(tmp_path))

    assert backend.loads == 2


def test_failed_check_is_not_remembered(tmp_path):
    """失敗した事前確認は覚えない。取得し終えれば次のページから読める"""
    root = tmp_path / "ndlocr"
    client = _client(root, FakeBackend())
    with pytest.raises(NdlocrNotInstalledError):
        client.ocr(_image(tmp_path))

    _install(root)

    assert client.ocr(_image(tmp_path)).text == "本文ノ列"


def test_recognition_error_is_ndlocr_error(tmp_path):
    """認識中の例外は NdlocrError になり、元の例外の種類とメッセージを含む"""
    backend = FakeBackend(recognize_errors={1: ValueError("broken tensor")})
    client = _client(_install(tmp_path / "ndlocr"), backend)

    with pytest.raises(NdlocrError) as excinfo:
        client.ocr(_image(tmp_path))

    assert "ValueError" in str(excinfo.value)
    assert "broken tensor" in str(excinfo.value)


def test_missing_image_is_image_error(tmp_path):
    """画像が無いときは既存の ImageFileError（認識まで進まない）"""
    backend = FakeBackend()
    client = _client(_install(tmp_path / "ndlocr"), backend)

    with pytest.raises(ImageFileError):
        client.ocr(tmp_path / "nothing.png")

    assert backend.recognized == []


def test_broken_image_is_image_error(tmp_path):
    """画像として開けないファイルも ImageFileError"""
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    client = _client(_install(tmp_path / "ndlocr"), FakeBackend())

    with pytest.raises(ImageFileError):
        client.ocr(broken)


# ---------- 版の取得 ----------


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path):
    """コミットが 1 つある git の作業ツリー（タグはまだ無い）"""
    if shutil.which("git") is None:
        pytest.skip("git が無い環境")
    repo = tmp_path / "ndlocr"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("x")
    _git(repo, "add", "README.md")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
    return repo


def test_version_is_read_from_tag(git_repo):
    """タグの付いたコミットなら、そのタグが版になる"""
    _git(git_repo, "tag", "1.3.1")

    assert read_ndlocr_version(git_repo) == "1.3.1"


def test_version_without_tag_is_unknown(git_repo):
    """タグの無いコミットなら「不明」"""
    assert read_ndlocr_version(git_repo) == "不明"


def test_version_without_git_is_unknown(git_repo, monkeypatch):
    """git が無ければ「不明」"""

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(ndlocr_client.subprocess, "run", no_git)

    assert read_ndlocr_version(git_repo) == "不明"


def test_version_of_plain_directory_is_unknown(tmp_path):
    """git の作業ツリーでない（手で置いた）なら、外側のリポジトリのタグを拾わず「不明」"""
    assert read_ndlocr_version(tmp_path) == "不明"
