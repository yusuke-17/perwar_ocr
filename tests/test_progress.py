"""進捗表示ヘルパー（D2）のテスト

進捗表示の見た目（rich の実描画）はテストしない。テスト実行時は非TTYなので
自然とフォールバック経路を通る＝「CI/リダイレクトで壊れない」ことの担保になる。
ここでは有効/無効の判定ロジックと、無効時フォールバックの振る舞いを確認する。
"""

import pytest

from utils import progress
from utils.progress import _progress_enabled, progress_active, spinner, track


class _FakeStdout:
    """isatty を制御できる差し替え用の擬似 stdout。"""

    def __init__(self, tty: bool):
        self._tty = tty
        self.buf: list[str] = []

    def isatty(self) -> bool:
        return self._tty

    def write(self, s: str) -> int:
        self.buf.append(s)
        return len(s)

    def flush(self) -> None:
        pass


def _force_tty(monkeypatch, tty: bool) -> None:
    """progress モジュールが見る sys.stdout を擬似 stdout に差し替える。"""
    monkeypatch.setattr(progress.sys, "stdout", _FakeStdout(tty))


# ---------- _progress_enabled ----------


def test_enabled_when_all_ok(monkeypatch):
    """NO_COLOR無し・設定ON・TTY のとき有効になる。"""
    monkeypatch.delenv("NO_COLOR", raising=False)
    _force_tty(monkeypatch, True)
    assert _progress_enabled() is True
    # 公開エイリアスも同じ判定を返す
    assert progress_active() is True


def test_disabled_by_no_color(monkeypatch):
    """NO_COLOR 環境変数があれば（TTYでも）無効。"""
    monkeypatch.setenv("NO_COLOR", "1")
    _force_tty(monkeypatch, True)
    assert _progress_enabled() is False


def test_disabled_by_config(monkeypatch):
    """設定 progress.enabled=false なら無効。"""
    monkeypatch.delenv("NO_COLOR", raising=False)
    _force_tty(monkeypatch, True)
    monkeypatch.setattr(
        progress.CONFIG,
        "get",
        lambda key, default=None: False if key == "progress.enabled" else default,
    )
    assert _progress_enabled() is False


def test_disabled_when_not_tty(monkeypatch):
    """非TTY（パイプ・リダイレクト）なら無効。"""
    monkeypatch.delenv("NO_COLOR", raising=False)
    _force_tty(monkeypatch, False)
    assert _progress_enabled() is False


# ---------- track フォールバック ----------


def test_track_fallback_yields_same_items(monkeypatch):
    """無効時、track は入力要素を同じ順でそのまま yield する。"""
    monkeypatch.setenv("NO_COLOR", "1")  # 確実に無効化
    result = list(track([1, 2, 3], total=3, description="x"))
    assert result == [1, 2, 3]


# ---------- spinner 例外時 ----------


def test_spinner_propagates_exception(monkeypatch):
    """無効時でも with ブロック内の例外はそのまま伝播する（表示は閉じる）。"""
    monkeypatch.setenv("NO_COLOR", "1")
    with pytest.raises(ValueError):
        with spinner("待機中"):
            raise ValueError("boom")
