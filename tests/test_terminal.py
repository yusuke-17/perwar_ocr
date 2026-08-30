"""ターミナル出力の共通判定（utils.terminal）のテスト

色を付けてよいかの4条件判定は diff 表示・検索結果表示の両方が使う。
判定を1か所に集約した以上、条件ごとの回帰をここで押さえる。
"""

import sys

import pytest

from utils.terminal import should_use_color


@pytest.fixture
def tty(monkeypatch):
    """標準出力が端末である状態を作る（他の条件だけを見られるようにする）"""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)


def test_color_on_tty_without_other_conditions(tty):
    assert should_use_color() is True


def test_no_color_flag_disables(tty):
    """条件1: --no-color の明示"""
    assert should_use_color(True) is False


def test_no_color_env_disables(tty, monkeypatch):
    """条件2: NO_COLOR 環境変数（https://no-color.org/ の慣行）"""
    monkeypatch.setenv("NO_COLOR", "1")
    assert should_use_color() is False


def test_config_disables(tty, monkeypatch):
    """条件3: 設定"""
    from utils import terminal

    monkeypatch.setattr(
        terminal.CONFIG, "get", lambda key, default=None: False, raising=False
    )
    assert should_use_color(config_key="search.color") is False


def test_non_tty_disables(monkeypatch):
    """条件4: 出力先が端末でない（パイプ・リダイレクト）"""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    assert should_use_color() is False


def test_config_key_omitted_skips_config_check(tty, monkeypatch):
    """config_key を渡さなければ設定は見ない"""
    from utils import terminal

    monkeypatch.setattr(
        terminal.CONFIG, "get", lambda key, default=None: False, raising=False
    )
    assert should_use_color() is True


def test_env_var_wins_over_enabled_config(tty, monkeypatch):
    """NO_COLOR は「その場限りの上書き」として設定より優先する"""
    monkeypatch.setenv("NO_COLOR", "1")
    assert should_use_color(config_key="search.color") is False
