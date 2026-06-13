"""
戦前日本語OCR 統合CLI（正面玄関）

すべての機能を `prewar` 1コマンドに集約する。

- 引数なしで実行 → 対話メニュー（矢印キーで選ぶ。暗記不要）
- サブコマンドで直接実行 → 慣れたユーザー向け（速い）

使い方:
    uv run prewar                      # 対話メニュー
    uv run prewar ocr input/画像.png    # OCR（画像→現代語）
    uv run prewar shoot                # 範囲スクショ撮りため（macOS）
    uv run prewar search 関東 震災      # ライブラリ全文検索
    uv run prewar index --rebuild       # 検索インデックス再構築
    uv run prewar stat                 # ライブラリ統計
    uv run prewar fix output/x.txt      # テキスト後処理（正規化/口語体化）
    uv run prewar check                # 環境チェック

各機能の中身は既存スクリプト（ocr_vision_llm / library / postprocess /
setup_check）に委譲する。引数定義は各スクリプトの add_arguments を流用し、
二重管理を避ける。既存の prewar-ocr / prewar-library は後方互換で残る。
"""

import argparse
import sys

import questionary

from scripts import library, ocr_vision_llm, postprocess, setup_check
from utils.config import CONFIG


# ---------- サブコマンド用ディスパッチャ ----------
# library の cmd_* は args.command を見ないので直呼びする（結合度が低い）。


def _run_shoot(args: argparse.Namespace) -> int:
    """shoot サブコマンド: OCRの撮りためモードを起動する"""
    args.image = "shoot"
    return ocr_vision_llm.run(args)


def _run_search(args: argparse.Namespace) -> int:
    return library.cmd_find(args)


def _run_index(args: argparse.Namespace) -> int:
    return library.cmd_index(args)


def _run_stat(args: argparse.Namespace) -> int:
    return library.cmd_stat(args)


# ---------- パーサ構築 ----------


def build_parser() -> argparse.ArgumentParser:
    """統合CLIの argparse パーサを組み立てる"""
    parser = argparse.ArgumentParser(
        prog="prewar",
        description="戦前日本語OCR 統合CLI（引数なしで対話メニュー）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  uv run prewar                      # 対話メニュー（おすすめ）
  uv run prewar ocr input/画像.png    # OCR（画像→現代語）
  uv run prewar shoot                # 範囲スクショ撮りため（macOS）
  uv run prewar search 関東 震災      # ライブラリ全文検索
  uv run prewar index --rebuild       # 検索インデックス再構築
  uv run prewar stat                 # ライブラリ統計
  uv run prewar fix output/x.txt      # テキスト後処理（正規化/口語体化）
  uv run prewar check                # 環境チェック
        """,
    )

    sub = parser.add_subparsers(dest="command")

    # ocr（= prewar-ocr）
    p_ocr = sub.add_parser("ocr", help="画像をOCRして現代語化")
    ocr_vision_llm.add_arguments(p_ocr)
    p_ocr.set_defaults(func=ocr_vision_llm.run)

    # shoot（= prewar-ocr shoot）
    p_shoot = sub.add_parser("shoot", help="範囲スクショを撮りため一括処理（macOS）")
    ocr_vision_llm.add_arguments(p_shoot)
    p_shoot.set_defaults(func=_run_shoot)

    # search（= prewar-library find）
    p_search = sub.add_parser("search", help="ライブラリを全文検索")
    library.add_find_arguments(p_search)
    library.add_library_root_argument(p_search)
    p_search.set_defaults(func=_run_search)

    # index（= prewar-library index）
    p_index = sub.add_parser("index", help="検索インデックスを更新")
    library.add_index_arguments(p_index)
    library.add_library_root_argument(p_index)
    p_index.set_defaults(func=_run_index)

    # stat（= prewar-library stat）
    p_stat = sub.add_parser("stat", help="ライブラリの統計情報を表示")
    library.add_library_root_argument(p_stat)
    p_stat.set_defaults(func=_run_stat)

    # fix（= postprocess）
    p_fix = sub.add_parser("fix", help="OCRテキストを正規化/口語体化")
    postprocess.add_arguments(p_fix)
    p_fix.set_defaults(func=postprocess.run)

    # check（= setup_check）
    p_check = sub.add_parser("check", help="環境を確認する")
    p_check.set_defaults(func=setup_check.run)

    return parser


# ---------- 対話メニュー ----------


def _defaults_for(add_args_fn, stub: list[str] | None = None) -> argparse.Namespace:
    """指定の add_arguments でパーサを作り、デフォルト値で埋めた Namespace を返す。

    属性の取りこぼし（AttributeError）を構造的に防ぎ、デフォルト値の
    二重管理（cli.py 側へのハードコード）も避けるためのヘルパー。
    必須の位置引数がある場合は stub にダミー値を渡す（後で上書きする前提）。
    """
    p = argparse.ArgumentParser()
    add_args_fn(p)
    return p.parse_args(stub or [])


def _menu_ocr() -> int:
    """OCR: 既存の対話フロー（select_mode_interactive 等）をそのまま使う"""
    args = _defaults_for(ocr_vision_llm.add_arguments)
    args.image = None  # → run() 内の対話モード分岐に乗る
    return ocr_vision_llm.run(args)


def _menu_shoot() -> int:
    args = _defaults_for(ocr_vision_llm.add_arguments)
    args.image = "shoot"
    return ocr_vision_llm.run(args)


def _menu_search() -> int:
    answer = questionary.text("検索語（スペース区切りでAND検索）:").ask()
    if not answer or not answer.strip():
        print("検索語が空のため中止しました。")
        return 0
    args = _defaults_for(library.add_find_arguments, stub=["__stub__"])
    args.library_root = CONFIG.get("paths.library")
    args.query = answer.split()
    return library.cmd_find(args)


def _menu_fix() -> int:
    target = questionary.path("対象テキストファイル/フォルダ:").ask()
    if not target or not target.strip():
        print("入力が空のため中止しました。")
        return 0
    modernize = questionary.confirm(
        "口語体変換（LLMリライト）も行いますか？", default=False
    ).ask()
    if modernize is None:
        return 0
    args = _defaults_for(postprocess.add_arguments, stub=["__stub__"])
    args.input = target.strip()
    args.modernize = modernize
    return postprocess.run(args)


def interactive_menu() -> int:
    """引数なし実行時の対話メニュー"""
    actions = {
        "OCR（画像を読む）": _menu_ocr,
        "撮りため（範囲スクショ・macOS）": _menu_shoot,
        "検索（ライブラリ全文検索）": _menu_search,
        "口語体変換（テキスト後処理）": _menu_fix,
        "環境確認": setup_check.main,
        "終了": None,
    }

    choice = questionary.select(
        "戦前OCRツール — 何をしますか？",
        choices=list(actions.keys()),
    ).ask()

    if choice is None or choice == "終了":
        return 0

    return actions[choice]()


# ---------- エントリポイント ----------


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "func", None) is None:
        # サブコマンド未指定 → 対話メニュー
        return interactive_menu()

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
