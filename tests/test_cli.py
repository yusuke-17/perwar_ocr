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


@pytest.mark.parametrize("value", ["none", "otsu", "adaptive"])
def test_binarize_accepts_valid_values(parser, value):
    args = parser.parse_args(["ocr", "input/p001.png", "--binarize", value])
    assert args.binarize == value


@pytest.mark.parametrize(
    "option", [["--on-page-error", "retry"], ["--binarize", "sauvola"]]
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
