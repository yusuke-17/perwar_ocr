"""統合CLI（prewar）のテスト（E1）

各サブコマンドが正しい処理に繋がっていること、対話メニュー用の既定値の
引数が処理に必要な項目を欠かさず持つことを確かめる。
対話メニュー（questionary による矢印キー選択）そのものはテストしない。
"""

import argparse

import pytest

from scripts import (
    cli,
    clean,
    diff_viewer,
    ocr_vision_llm,
    postprocess,
    setup_check,
)


@pytest.fixture
def parser() -> argparse.ArgumentParser:
    return cli.build_parser()


# ---------- サブコマンドの振り分け ----------


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["ocr", "input/p001.png"], ocr_vision_llm.run),
        (["shoot"], cli._run_shoot),
        (["search", "関東地方"], cli._run_search),
        (["index"], cli._run_index),
        (["stat"], cli._run_stat),
        (["fix", "output/x.txt"], postprocess.run),
        (["diff", "2026-09-21_p001"], diff_viewer.run),
        (["clean", "input"], clean.run),
        (["check"], setup_check.run),
    ],
)
def test_subcommand_dispatches_to_handler(parser, argv, expected):
    """サブコマンドごとに、期待する処理関数が func に入る"""
    assert parser.parse_args(argv).func is expected


def test_no_subcommand_has_no_func(parser):
    """サブコマンド無し → func が無く、main は対話メニューへ進む"""
    assert getattr(parser.parse_args([]), "func", None) is None


# ---------- 既定値の引数（対話メニュー経由） ----------

# OCR 処理（scripts/ocr_vision_llm.py）が args から参照する全属性
OCR_ARG_NAMES = [
    "image",
    "model",
    "prompt",
    "output",
    "library_root",
    "no_preprocess",
    "binarize",
    "no_normalize",
    "no_modernize",
    "legacy_output",
    "no_save",
    "no_run",
    "separate",
    "on_page_error",
    "order",
]


@pytest.mark.parametrize("name", OCR_ARG_NAMES)
def test_menu_defaults_have_all_ocr_args(name):
    """対話メニュー用の既定値 Namespace が OCR 処理の参照する属性を全部持つ

    cli._defaults_for が防ごうとしている AttributeError の回帰テスト。
    """
    args = cli._defaults_for(ocr_vision_llm.add_arguments)
    assert hasattr(args, name)


def test_ocr_subcommand_has_all_ocr_args(parser):
    """サブコマンド経由でも同じ属性が揃う（add_arguments の共有が崩れていない）"""
    args = parser.parse_args(["ocr", "input/p001.png"])
    missing = [n for n in OCR_ARG_NAMES if not hasattr(args, n)]
    assert missing == []


# ---------- 選択肢の検証 ----------


@pytest.mark.parametrize("value", ["skip", "abort"])
def test_on_page_error_accepts_valid_values(parser, value):
    args = parser.parse_args(["ocr", "input/p001.png", "--on-page-error", value])
    assert args.on_page_error == value


@pytest.mark.parametrize("value", ["name", "mtime"])
def test_order_accepts_valid_values(parser, value):
    args = parser.parse_args(["ocr", "input/p001.png", "--order", value])
    assert args.order == value


def test_order_defaults_to_unspecified(parser):
    """未指定は None（config.toml の値と区別するため）"""
    assert parser.parse_args(["ocr", "input/p001.png"]).order is None


@pytest.mark.parametrize("value", ["none", "otsu", "adaptive"])
def test_binarize_accepts_valid_values(parser, value):
    args = parser.parse_args(["ocr", "input/p001.png", "--binarize", value])
    assert args.binarize == value


@pytest.mark.parametrize(
    "option",
    [["--on-page-error", "retry"], ["--binarize", "sauvola"], ["--order", "random"]],
)
def test_invalid_choice_is_rejected(parser, option, capsys):
    """選択肢に無い値は argparse がエラーにする（終了コード2）"""
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["ocr", "input/p001.png", *option])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


# ---------- shoot の委譲 ----------


def test_run_shoot_sets_image_to_shoot(parser, monkeypatch):
    """shoot サブコマンドは args.image を 'shoot' にして OCR 処理へ渡す"""
    received: list[argparse.Namespace] = []

    def fake_run(args: argparse.Namespace) -> int:
        received.append(args)
        return 0

    monkeypatch.setattr(ocr_vision_llm, "run", fake_run)
    args = parser.parse_args(["shoot"])

    assert args.func(args) == 0
    assert len(received) == 1
    assert received[0].image == "shoot"


# ---------- 起動コマンドとヘルプ（G8） ----------


def test_only_prewar_command_is_installed():
    """起動コマンドは統合CLI `prewar` だけ（旧 prewar-ocr / prewar-library は無い）"""
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        scripts = tomllib.load(f)["project"]["scripts"]

    assert scripts == {"prewar": "scripts.cli:main"}


def test_search_help_explains_query_syntax(parser):
    """prewar search --help に検索構文（AND/OR/NOT/対象限定/3文字の注意）が出る"""
    sub_action = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    help_text = sub_action.choices["search"].format_help()

    for expected in ("OR", "NOT", "原文:", "3文字以上", "uv run prewar search"):
        assert expected in help_text
    assert "prewar-library" not in help_text


# ---------- ページ順の解決（D5） ----------


def _config_returning(monkeypatch, order):
    """CONFIG の batch.order だけを差し替える（他のキーは本物の値を返す）"""
    real_get = ocr_vision_llm.CONFIG.get

    def fake_get(key, default=None):
        if key == "batch.order":
            return order
        return real_get(key, default)

    monkeypatch.setattr(ocr_vision_llm.CONFIG, "get", fake_get)


def _ocr_args(order=None) -> argparse.Namespace:
    args = cli._defaults_for(ocr_vision_llm.add_arguments)
    args.order = order
    return args


def test_order_defaults_to_name_in_config():
    """設定ファイルに何も書かなければ、既定の並べ方はファイル名の自然順"""
    assert ocr_vision_llm.CONFIG.get("batch.order") == "name"
    assert ocr_vision_llm._resolve_order(_ocr_args()) == "name"


def test_order_flag_overrides_config(monkeypatch):
    """実行時のオプション > 設定ファイル"""
    _config_returning(monkeypatch, "mtime")
    assert ocr_vision_llm._resolve_order(_ocr_args()) == "mtime"
    assert ocr_vision_llm._resolve_order(_ocr_args("name")) == "name"


def test_invalid_order_in_config_is_an_error(monkeypatch):
    """設定ファイルの値が未知なら、黙って既定値に戻さず使える値を示すエラーにする"""
    from utils.config import ConfigError

    _config_returning(monkeypatch, "random")
    with pytest.raises(ConfigError) as exc:
        ocr_vision_llm._resolve_order(_ocr_args())
    assert "name" in str(exc.value) and "mtime" in str(exc.value)


def test_run_stops_before_ocr_when_order_in_config_is_invalid(monkeypatch, capsys):
    """設定が不正なら OCR を始めず（画像を読まず）終了コード 1"""
    _config_returning(monkeypatch, "random")
    started: list[object] = []
    monkeypatch.setattr(
        ocr_vision_llm, "process_folder", lambda *a, **k: started.append(a) or 0
    )
    monkeypatch.setattr(
        ocr_vision_llm, "process_single", lambda *a, **k: started.append(a) or 0
    )
    args = _ocr_args()
    args.image = "input/p001.png"

    assert ocr_vision_llm.run(args) == 1
    assert started == []
    assert "batch.order" in capsys.readouterr().out
