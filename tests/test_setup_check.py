"""環境確認（prewar check）の合否判定のテスト

各 check_* を差し替えて、Ollama にも実環境の依存にも NDLOCR-Lite にも触れずに
「選ばれた OCR エンジンを含む必須項目だけで合否を決める」「選ばれていないエンジンは合否に数えない」を確かめる。
"""

import sys

import pytest

from scripts import setup_check
from utils import ndlocr_client
from utils.config import _DEFAULTS, Config, _deep_merge
from utils.ndlocr_client import INSTALL_HINT, NdlocrNotInstalledError


def _use_engine(monkeypatch, engine: str) -> None:
    """[models] ocr を差し替える（手元の config.toml に左右されない）"""
    monkeypatch.setattr(
        setup_check, "CONFIG", Config(_deep_merge(_DEFAULTS, {"models": {"ocr": engine}}))
    )


@pytest.fixture
def all_required_ok(monkeypatch):
    """既定のエンジン（NDLOCR-Lite）で、必須項目がすべて合格・GLM-OCR も取得済みの状態を作る。

    GLM-OCR の簡易テスト（check_glm_ocr）が呼ばれたかを記録するリストを返す。
    """
    glm_calls = []
    _use_engine(monkeypatch, "ndlocr-lite")
    monkeypatch.setattr(setup_check, "check_python_version", lambda: True)
    monkeypatch.setattr(setup_check, "check_packages", lambda: True)
    monkeypatch.setattr(
        setup_check, "check_ollama_connection", lambda: (True, ["glm-ocr:latest"])
    )

    def fake_glm(model_names, model="glm-ocr"):
        glm_calls.append((model_names, model))
        return True

    monkeypatch.setattr(setup_check, "check_glm_ocr", fake_glm)
    monkeypatch.setattr(ndlocr_client, "verify_installation", lambda: ndlocr_client.ndlocr_path())
    monkeypatch.setattr(ndlocr_client, "read_ndlocr_version", lambda root: "1.3.1")
    return glm_calls


def _not_installed(monkeypatch):
    """NDLOCR-Lite を取得していない状態にする"""

    def raise_not_installed():
        raise NdlocrNotInstalledError(f"NDLOCR-Lite のソースが見つかりません: vendor/ndlocr-lite\n{INSTALL_HINT}")

    monkeypatch.setattr(ndlocr_client, "verify_installation", raise_not_installed)


def test_all_required_ok_with_ndlocr(all_required_ok, capsys):
    """揃っていれば合格。NDLOCR-Lite の版が出て、選ばれていない GLM-OCR の簡易テストはしない"""
    assert setup_check.main() == 0

    out = capsys.readouterr().out
    assert "NDLOCR-Lite（選択中）" in out
    assert "版: 1.3.1" in out
    assert "✓ 取得済み: glm-ocr:latest" in out
    assert "すべてのチェックをパスしました" in out
    assert all_required_ok == []


def test_ollama_down_fails_and_skips_glm(all_required_ok, monkeypatch, capsys):
    """Ollama に接続できなければ不合格（口語化に要る）。GLM-OCR の確認は飛ばす"""
    monkeypatch.setattr(setup_check, "check_ollama_connection", lambda: (False, []))

    assert setup_check.main() == 1
    assert all_required_ok == []
    out = capsys.readouterr().out
    assert "✗ Ollama 接続" in out
    assert "スキップ（Ollama 未接続）" in out


def test_default_engine_not_installed_fails(all_required_ok, monkeypatch, capsys):
    """既定の NDLOCR-Lite が未導入なら導入方法つきで不合格。GLM-OCR は取得済みと表示される"""
    _not_installed(monkeypatch)

    assert setup_check.main() == 1
    out = capsys.readouterr().out
    assert "✗ NDLOCR-Lite のソースが見つかりません" in out
    assert "git submodule update --init --depth 1" in out
    assert "✓ 取得済み: glm-ocr:latest" in out
    assert "✗ NDLOCR-Lite" in out


def test_glm_selected_does_not_require_ndlocr(all_required_ok, monkeypatch, capsys):
    """GLM-OCR を選んでいれば、NDLOCR-Lite が未導入でも「未導入」と出るだけで合格"""
    _use_engine(monkeypatch, "glm-ocr")
    _not_installed(monkeypatch)

    assert setup_check.main() == 0
    assert all_required_ok == [(["glm-ocr:latest"], "glm-ocr")]  # 選ばれたモデルの簡易テストをする
    out = capsys.readouterr().out
    assert "OCR モデル glm-ocr（選択中）" in out
    assert "未導入（任意）" in out
    assert "−（未導入） NDLOCR-Lite（任意）" in out


def test_glm_selected_and_ollama_down_fails(all_required_ok, monkeypatch, capsys):
    """GLM-OCR を選んでいて Ollama に接続できなければ、OCR エンジンも不合格"""
    _use_engine(monkeypatch, "glm-ocr")
    monkeypatch.setattr(setup_check, "check_ollama_connection", lambda: (False, []))

    assert setup_check.main() == 1
    assert "✗ OCR モデル glm-ocr" in capsys.readouterr().out


def test_missing_required_package_fails(all_required_ok, monkeypatch):
    """必須パッケージが欠けていれば終了コード 1"""
    monkeypatch.setattr(setup_check, "check_packages", lambda: False)

    assert setup_check.main() == 1


def test_required_packages_match_actual_use():
    """確認対象は実際に使う必須依存（NDLOCR-Lite の実行に要るものを含む）。

    NDLOCR-Lite の公式の依存のうち、画像の OCR に使わない PDF・GUI 関係（reportlab・flet など）は含めない。
    """
    modules = set(setup_check.REQUIRED_PACKAGES)

    assert {"ollama", "httpx", "cv2", "numpy", "jaconv", "senzen_word", "questionary", "rich",
            "onnxruntime", "PIL", "yaml", "lxml", "networkx", "tqdm"} == modules
    assert not {"reportlab", "flet", "pypdf", "pypdfium2"} & modules


def test_check_packages_reports_missing(monkeypatch, capsys):
    """入っていないパッケージがあれば False と uv sync の案内"""
    monkeypatch.setattr(
        setup_check, "REQUIRED_PACKAGES", {"no_such_module_xyz": "no-such-package"}
    )

    assert setup_check.check_packages() is False
    out = capsys.readouterr().out
    assert "no-such-package" in out
    assert "uv sync" in out


def test_missing_onnxruntime_is_reported(monkeypatch, capsys):
    """NDLOCR-Lite の推論に使う onnxruntime が無ければ、導入方法つきで不合格"""
    # sys.modules に None を入れると、その名前の import は ImportError になる
    monkeypatch.setitem(sys.modules, "onnxruntime", None)

    assert setup_check.check_packages() is False
    assert "✗ onnxruntime がインポートできません → uv sync" in capsys.readouterr().out


def test_check_ndlocr_shows_version(monkeypatch, capsys):
    """NDLOCR-Lite の確認では版を表示する（モデルは読み込まない＝verify_installation だけ）"""
    monkeypatch.setattr(ndlocr_client, "verify_installation", lambda: ndlocr_client.ndlocr_path())
    monkeypatch.setattr(ndlocr_client, "read_ndlocr_version", lambda root: "1.3.1")

    assert setup_check.check_ndlocr() is True
    assert "版: 1.3.1" in capsys.readouterr().out


# ---------- Ollama のバージョン表示（G12） ----------


class _FakeListClient:
    """list() にモデル名を返し、_request_raw（/api/version）は指定どおりに振る舞う"""

    def __init__(self, version: str | None = "0.40.2"):
        self.version = version

    def list(self):
        class _Entry:
            model = "glm-ocr:latest"

        class _Models:
            models = [_Entry()]

        return _Models()

    def _request_raw(self, method, url):
        if self.version is None:
            raise RuntimeError("404 page not found")

        version = self.version

        class _Response:
            def json(self):
                return {"version": version}

        return _Response()


def test_ollama_version_is_shown(monkeypatch, capsys):
    """仕様「Ollama に接続できる」: 接続確認とともにバージョンが出る"""
    from utils import ollama_client

    monkeypatch.setattr(ollama_client, "list_client", lambda: _FakeListClient())

    ok, names = setup_check.check_ollama_connection()

    assert ok is True
    assert names == ["glm-ocr:latest"]
    assert "バージョン: 0.40.2" in capsys.readouterr().out


def test_unknown_version_does_not_fail(monkeypatch, capsys):
    """仕様「バージョンが取得できない」: 「不明」と出て、接続確認は合格のまま"""
    from utils import ollama_client

    monkeypatch.setattr(
        ollama_client, "list_client", lambda: _FakeListClient(version=None)
    )

    ok, _ = setup_check.check_ollama_connection()

    assert ok is True
    assert "バージョン: 不明" in capsys.readouterr().out
