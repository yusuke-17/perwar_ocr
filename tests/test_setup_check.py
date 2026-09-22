"""環境確認（prewar check）の合否判定のテスト

各 check_* を差し替えて、Ollama にも実環境の依存にも触れずに
「必須項目だけで合否を決める」「任意項目（Surya）は合否に数えない」を確かめる。
"""

import pytest

from scripts import setup_check


@pytest.fixture
def all_required_ok(monkeypatch):
    """必須項目がすべて合格、Surya は未導入の状態を作る。

    GLM-OCR の確認が呼ばれたかを記録するリストを返す。
    """
    glm_calls = []
    monkeypatch.setattr(setup_check, "check_python_version", lambda: True)
    monkeypatch.setattr(setup_check, "check_packages", lambda: True)
    monkeypatch.setattr(
        setup_check, "check_ollama_connection", lambda: (True, ["glm-ocr:latest"])
    )

    def fake_glm(model_names):
        glm_calls.append(model_names)
        return True

    monkeypatch.setattr(setup_check, "check_glm_ocr", fake_glm)
    monkeypatch.setattr(setup_check, "check_surya", lambda: False)
    return glm_calls


def test_surya_missing_still_passes(all_required_ok, capsys):
    """必須が揃っていれば、Surya 未導入でも終了コード 0"""
    assert setup_check.main() == 0

    out = capsys.readouterr().out
    assert "Surya OCR（任意）" in out
    assert "未導入" in out
    assert "すべてのチェックをパスしました" in out


def test_surya_installed_passes(all_required_ok, monkeypatch, capsys):
    """Surya 導入済みなら ✓ 表示で終了コード 0"""
    monkeypatch.setattr(setup_check, "check_surya", lambda: True)

    assert setup_check.main() == 0
    assert "✓ Surya OCR（任意）" in capsys.readouterr().out


def test_ollama_down_fails_and_skips_glm(all_required_ok, monkeypatch, capsys):
    """Ollama に接続できなければ GLM-OCR の確認を飛ばし、終了コード 1"""
    monkeypatch.setattr(setup_check, "check_ollama_connection", lambda: (False, []))

    assert setup_check.main() == 1
    assert all_required_ok == []  # GLM-OCR の確認は呼ばれない
    assert "✗ Ollama 接続" in capsys.readouterr().out


def test_missing_required_package_fails(all_required_ok, monkeypatch):
    """必須パッケージが欠けていれば終了コード 1"""
    monkeypatch.setattr(setup_check, "check_packages", lambda: False)

    assert setup_check.main() == 1


def test_required_packages_match_actual_use():
    """確認対象は実際に使う必須依存。使っていない Pillow は含めない"""
    modules = set(setup_check.REQUIRED_PACKAGES)

    assert "PIL" not in modules
    assert {"ollama", "httpx", "cv2", "numpy", "jaconv", "senzen_word",
            "questionary", "rich"} == modules


def test_check_packages_reports_missing(monkeypatch, capsys):
    """入っていないパッケージがあれば False と uv sync の案内"""
    monkeypatch.setattr(
        setup_check, "REQUIRED_PACKAGES", {"no_such_module_xyz": "no-such-package"}
    )

    assert setup_check.check_packages() is False
    out = capsys.readouterr().out
    assert "no-such-package" in out
    assert "uv sync" in out


def test_check_surya_not_installed(monkeypatch, capsys):
    """Surya 未導入なら False と導入方法の案内（import はしない）"""
    monkeypatch.setattr(setup_check.importlib.util, "find_spec", lambda name: None)

    assert setup_check.check_surya() is False
    assert "uv sync --extra surya" in capsys.readouterr().out
